import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime, date
import io
import time

# --- 設定 ---
GAS_URL = st.secrets["gas"]["url"]
GAS_API_KEY = st.secrets["gas"]["api_key"]
CURRENT_WORKSHEET_NAME = "Sheet_miso" # 通常の語彙シート名
TEST_RESULTS_SHEET_PREFIX = "Sheet_TestResults_" # テスト結果シート名のプレフィックス

# ヘッダー定義
VOCAB_HEADERS = ['ID', '用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)', '学習進捗 (Progress)']
TEST_RESULTS_HEADERS = ['Date', 'Category', 'TestType', 'Score', 'TotalQuestions', 'Details']

# --- GASとの連携関数 ---
def read_data_from_gas(sheet_name):
    try:
        response = requests.get(GAS_URL, params={'api_key': GAS_API_KEY, 'sheet': sheet_name})
        response.raise_for_status() # HTTPエラーがあれば例外を発生させる
        data = response.json()
        
        if "error" in data:
            if data["error"].startswith("シートが見つかりません"):
                st.warning(f"指定されたシート '{sheet_name}' が見つかりませんでした。新規作成します。", icon="⚠️")
                # 新しいDataFrameを作成し、ヘッダーを設定
                if sheet_name.startswith(TEST_RESULTS_SHEET_PREFIX):
                    return pd.DataFrame(columns=TEST_RESULTS_HEADERS)
                else:
                    return pd.DataFrame(columns=VOCAB_HEADERS)
            else:
                st.error(f"GASからのデータ読み込み中にエラーが発生しました: {data['error']}")
                return None
        
        df = pd.DataFrame(data['data'])
        
        # IDカラムが存在し、かつ数値として扱える場合はInt64に変換
        if 'ID' in df.columns:
            # 空文字列をNaNに変換してからInt64に変換
            df['ID'] = pd.to_numeric(df['ID'], errors='coerce').astype('Int64')
        
        # 'Date' カラムを datetime オブジェクトに変換 (テスト結果シートの場合)
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')

        # 'Details' カラムのJSON文字列をリストに戻す
        if 'Details' in df.columns:
            df['Details'] = df['Details'].apply(lambda x: json.loads(x) if pd.notna(x) and isinstance(x, str) else [])

        return df
    except requests.exceptions.RequestException as e:
        st.error(f"GASへの接続エラーまたは通信エラーが発生しました: {e}")
        return None
    except json.JSONDecodeError as e:
        st.error(f"GASからのレスポンスをJSONとして解析できませんでした: {e}. レスポンス: {response.text}")
        return None
    except Exception as e:
        st.error(f"データの読み込み中に予期せぬエラーが発生しました: {e}")
        return None

def write_data_to_gas(df, sheet_name):
    # 送信するDataFrameをGASに適した形式に変換
    # ヘッダー行とデータ行を結合
    df_to_send = df.copy()

    # datetimeオブジェクトとdateオブジェクトをISOフォーマット文字列に変換
    # DetailsカラムのリストをJSON文字列に変換
    for col in df_to_send.columns:
        if pd.api.types.is_datetime64_any_dtype(df_to_send[col]):
            df_to_send[col] = df_to_send[col].dt.isoformat()
        elif df_to_send[col].apply(lambda x: isinstance(x, date) and not isinstance(x, datetime)).any():
             df_to_send[col] = df_to_send[col].apply(lambda x: x.isoformat() if isinstance(x, date) else x)
        elif col == 'Details': # DetailsカラムはJSON文字列に変換
            df_to_send[col] = df_to_send[col].apply(lambda x: json.dumps(x) if isinstance(x, list) else x)

    # NaNを空文字列またはNoneに変換
    # Int64 (大文字I) はPandasのNullable Integerで、NaNを保持できるため、
    # その他の型でNaNを空文字列に変換する
    processed_data = []
    processed_data.append(df_to_send.columns.tolist()) # ヘッダーを追加

    # データ本体の変換
    for _, row in df_to_send.iterrows():
        processed_row = []
        for item in row:
            if pd.isna(item): # スカラー値のNaNのみをチェック
                processed_row.append("") # NaNを空文字列に
            elif isinstance(item, (datetime, pd.Timestamp, date)): # datetimeやdateオブジェクトをisoformatで文字列化
                processed_row.append(item.isoformat())
            else:
                processed_row.append(item)
        processed_data.append(processed_row)

    try:
        response = requests.post(
            GAS_URL, 
            params={'api_key': GAS_API_KEY, 'sheet': sheet_name}, 
            json={'data': processed_data}
        )
        response.raise_for_status() # HTTPエラーがあれば例外を発生させる
        data = response.json()
        if "error" in data:
            st.error(f"GASへのデータ書き込み中にエラーが発生しました: {data['error']}")
            return False
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"GASへの接続エラーまたは通信エラーが発生しました: {e}")
        return False
    except json.JSONDecodeError as e:
        st.error(f"GASからのレスポンスをJSONとして解析できませんでした: {e}. レスポンス: {response.text}")
        return False
    except Exception as e:
        st.error(f"データの書き込み中に予期せぬエラーが発生しました: {e}. Python側でのデータ処理中にエラーが発生した可能性があります。")
        return False


# --- アプリケーションの状態管理と初期化 ---
def initialize_session_state():
    if "current_worksheet_name" not in st.session_state:
        st.session_state.current_worksheet_name = CURRENT_WORKSHEET_NAME
    if "df_vocab" not in st.session_state:
        st.session_state.df_vocab = pd.DataFrame(columns=VOCAB_HEADERS)
    if "df_test_results" not in st.session_state:
        st.session_state.df_test_results = pd.DataFrame(columns=TEST_RESULTS_HEADERS)
    if "last_vocab_id" not in st.session_state:
        st.session_state.last_vocab_id = 0
    if "test_mode" not in st.session_state:
        st.session_state.test_mode = None # テストモードの状態を管理
    if "current_page" not in st.session_state:
        st.session_state.current_page = "データ管理" # 初期ページ

# データのリロード関数
def reload_data():
    st.session_state.df_vocab = read_data_from_gas(st.session_state.current_worksheet_name)
    if st.session_state.df_vocab is None: # 読み込み失敗時は空のDataFrameで初期化
        st.session_state.df_vocab = pd.DataFrame(columns=VOCAB_HEADERS)
    
    # IDの最大値を更新
    if 'ID' in st.session_state.df_vocab.columns and not st.session_state.df_vocab['ID'].dropna().empty:
        st.session_state.last_vocab_id = st.session_state.df_vocab['ID'].dropna().max()
    else:
        st.session_state.last_vocab_id = 0

    st.session_state.df_test_results = read_data_from_gas(TEST_RESULTS_SHEET_PREFIX + st.session_state.current_worksheet_name.replace("Sheet_", ""))
    if st.session_state.df_test_results is None: # 読み込み失敗時は空のDataFrameで初期化
        st.session_state.df_test_results = pd.DataFrame(columns=TEST_RESULTS_HEADERS)

# --- Streamlit UI ---
st.set_page_config(layout="wide")
st.title("ビジネス用語集ビルダー")

initialize_session_state()

# 初回データ読み込み (もしくはリロード時)
if "data_loaded" not in st.session_state or not st.session_state.data_loaded:
    with st.spinner("データを読み込み中..."):
        reload_data()
    st.session_state.data_loaded = True

# --- ページ切り替え ---
with st.sidebar:
    st.header("ナビゲーション")
    if st.button("データ管理", key="nav_data_management"):
        st.session_state.current_page = "データ管理"
        st.session_state.test_mode = None # テストモードを終了
    if st.button("テストモード", key="nav_test_mode"):
        st.session_state.current_page = "テストモード"
        st.session_state.test_mode = {'started': False} # テストモード開始準備
    
    st.markdown("---")
    st.header("ワークシート設定")
    new_sheet_name = st.text_input("現在のワークシート名", st.session_state.current_worksheet_name)
    if st.button("ワークシート切り替え"):
        st.session_state.current_worksheet_name = new_sheet_name
        st.session_state.data_loaded = False # データ再読み込みをトリガー
        reload_data()
        st.rerun()

# --- データ管理ページ ---
if st.session_state.current_page == "データ管理":
    st.header("データ管理")
    
    # データフレーム表示
    st.subheader("用語集")
    edited_df = st.data_editor(
        st.session_state.df_vocab,
        column_config={
            "ID": st.column_config.NumberColumn("ID", help="自動採番されます", disabled=True),
            "用語 (Term)": st.column_config.TextColumn("用語 (Term)", required=True),
            "説明 (Definition)": st.column_config.TextColumn("説明 (Definition)", required=True),
            "例文 (Example)": st.column_config.TextColumn("例文 (Example)", help="例: 顧客を**リード**する。"),
            "カテゴリ (Category)": st.column_config.TextColumn("カテゴリ (Category)"),
            "学習進捗 (Progress)": st.column_config.SelectboxColumn(
                "学習進捗 (Progress)",
                options=["Not Started", "Learning", "Mastered"],
                default="Not Started",
                required=True,
            ),
        },
        num_rows="dynamic",
        use_container_width=True,
        key="vocab_editor"
    )

    if st.button("変更を保存"):
        # IDが空の行に新しいIDを割り当てる
        current_max_id = st.session_state.last_vocab_id
        for i in range(len(edited_df)):
            if pd.isna(edited_df.loc[i, 'ID']) or edited_df.loc[i, 'ID'] == "":
                current_max_id += 1
                edited_df.loc[i, 'ID'] = current_max_id
        
        # 不要な行（IDがNaNまたは空の行）を削除
        edited_df = edited_df.dropna(subset=['ID'])
        
        # IDカラムをInt64型に戻す（GAS書き込み時にNaNが空文字列になるのを防ぐため）
        edited_df['ID'] = pd.to_numeric(edited_df['ID'], errors='coerce').astype('Int64')

        if write_data_to_gas(edited_df, st.session_state.current_worksheet_name):
            st.success(f"データがスプレッドシート '{st.session_state.current_worksheet_name}' に保存されました！")
            st.session_state.df_vocab = edited_df # セッション状態も更新
            st.session_state.last_vocab_id = current_max_id # 最大IDを更新
            st.rerun() # 変更を反映するために再実行
        else:
            st.error("データの保存に失敗しました。")

    st.subheader("テスト結果")
    if not st.session_state.df_test_results.empty:
        # 詳細表示用の展開機能付きデータエディタ
        st.dataframe(
            st.session_state.df_test_results.drop(columns=['Details']), # Detailsは最初は表示しない
            use_container_width=True
        )
        
        # 各テスト結果の詳細を展開して表示する機能
        with st.expander("テスト結果の詳細を確認する"):
            for i, row in st.session_state.df_test_results.iterrows():
                st.subheader(f"テスト結果 {i+1}: {row['Date'].strftime('%Y/%m/%d %H:%M')}")
                st.write(f"**カテゴリ:** {row['Category']}")
                st.write(f"**テスト形式:** {row['TestType']}")
                st.write(f"**スコア:** {row['Score']} / {row['TotalQuestions']}")
                
                details_df = pd.DataFrame(row['Details'])
                if not details_df.empty:
                    # 'term_id', 'term_name', 'term_definition', 'term_example' も表示に追加
                    display_details_df = details_df[['question_text', 'correct_answer', 'user_answer', 'is_correct', 'term_name', 'term_definition', 'term_example']].copy()
                    display_details_df.columns = ['問題', '正解', 'あなたの回答', '正誤', '用語名', '用語説明', '例文']
                    st.dataframe(display_details_df, use_container_width=True)
                else:
                    st.info("このテストの詳細は記録されていません。")
                st.markdown("---")
    else:
        st.info("まだテスト結果がありません。")

    # CSVダウンロード機能
    st.subheader("CSVエクスポート")
    csv_data = st.session_state.df_vocab.to_csv(index=False, encoding='utf-8-sig')
    st.download_button(
        label="用語集をCSVでダウンロード",
        data=csv_data,
        file_name=f"{st.session_state.current_worksheet_name}.csv",
        mime="text/csv",
    )

# --- テストモードページ ---
elif st.session_state.current_page == "テストモード":
    st.header("テストモード")

    test_results_sheet_name = TEST_RESULTS_SHEET_PREFIX + st.session_state.current_worksheet_name.replace("Sheet_", "")

    if st.session_state.df_vocab.empty:
        st.warning("用語集にデータがありません。データ管理ページから用語を追加してください。", icon="⚠️")
    else:
        if st.session_state.test_mode['started'] == False:
            st.subheader("テスト設定")
            all_categories = ['全カテゴリ'] + st.session_state.df_vocab['カテゴリ (Category)'].dropna().unique().tolist()
            selected_category = st.selectbox("カテゴリを選択", all_categories, key="test_category_select")
            
            num_questions_options = [5, 10, 15, 20, len(st.session_state.df_vocab)]
            num_questions_options = [n for n in num_questions_options if n <= len(st.session_state.df_vocab)]
            if not num_questions_options:
                num_questions_options = [0] # データがない場合は0
            num_questions = st.selectbox(
                "出題数", 
                num_questions_options, 
                index=min(1, len(num_questions_options) - 1) if num_questions_options else 0, # デフォルトを10問または最大数に
                key="test_num_questions"
            )

            test_type = st.radio(
                "テスト形式",
                [
                    ('用語→説明', 'term_to_def'),
                    ('例文→用語', 'example_to_term'),
                ],
                format_func=lambda x: x[0], # ラジオボタンには表示名、値にはキー
                key="test_type_radio"
            )[1] # 選択されたキーを取得

            if st.button("テスト開始", type="primary"):
                if num_questions == 0:
                    st.error("出題数が0です。用語集に用語を追加してください。")
                else:
                    # 質問リストを作成
                    filtered_df = st.session_state.df_vocab
                    if selected_category != '全カテゴリ':
                        filtered_df = st.session_state.df_vocab[st.session_state.df_vocab['カテゴリ (Category)'] == selected_category]
                        
                    if filtered_df.empty:
                        st.error(f"選択されたカテゴリ '{selected_category}' に用語がありません。")
                    elif len(filtered_df) < num_questions:
                        st.error(f"カテゴリ '{selected_category}' の用語が不足しています。（現在: {len(filtered_df)}個、要求: {num_questions}個）")
                    else:
                        questions_df = filtered_df.sample(n=num_questions, random_state=int(time.time()))
                        
                        questions = []
                        for _, row in questions_df.iterrows():
                            if test_type == 'term_to_def':
                                # 用語→説明
                                question_text = f"「{row['用語 (Term)']}」の説明として正しいものを選びなさい。"
                                correct_answer = row['説明 (Definition)']
                                # 間違った選択肢をランダムに選ぶ
                                other_definitions = filtered_df[filtered_df['ID'] != row['ID']]['説明 (Definition)'].sample(min(3, len(filtered_df) - 1)).tolist()
                                choices = list(set([correct_answer] + other_definitions)) # 正解と不正解を混ぜて重複を排除
                                if len(choices) < 4: # 選択肢が4つ未満の場合、さらにランダムな単語から補充
                                    all_definitions = st.session_state.df_vocab['説明 (Definition)'].sample(min(4 - len(choices), len(st.session_state.df_vocab))).tolist()
                                    choices.extend(all_definitions)
                                choices = list(set(choices)) # 再度重複排除
                                while len(choices) < 4 and len(st.session_state.df_vocab) > len(choices): # 少なくとも4つの選択肢を確保
                                    choices.append(st.session_state.df_vocab['説明 (Definition)'].sample(1).iloc[0])
                                    choices = list(set(choices))
                                choices = choices[:4] # 常に4つに限定
                                
                            elif test_type == 'example_to_term':
                                # 例文→用語
                                question_text = f"以下の例文の**太字**の用語は何ですか？\n\n「{row['例文 (Example)']}」"
                                correct_answer = row['用語 (Term)']
                                # 間違った選択肢をランダムに選ぶ
                                other_terms = filtered_df[filtered_df['ID'] != row['ID']]['用語 (Term)'].sample(min(3, len(filtered_df) - 1)).tolist()
                                choices = list(set([correct_answer] + other_terms))
                                if len(choices) < 4:
                                    all_terms = st.session_state.df_vocab['用語 (Term)'].sample(min(4 - len(choices), len(st.session_state.df_vocab))).tolist()
                                    choices.extend(all_terms)
                                choices = list(set(choices))
                                while len(choices) < 4 and len(st.session_state.df_vocab) > len(choices):
                                    choices.append(st.session_state.df_vocab['用語 (Term)'].sample(1).iloc[0])
                                    choices = list(set(choices))
                                choices = choices[:4]
                            
                            # 選択肢をシャッフル
                            import random
                            random.shuffle(choices)

                            questions.append({
                                'question_text': question_text,
                                'choices': choices,
                                'correct_answer': correct_answer,
                                'user_answer': None, # ユーザーの回答を格納
                                'term_id': row['ID'], # 用語のIDも保存
                                'term_name': row['用語 (Term)'],
                                'term_definition': row['説明 (Definition)'],
                                'term_example': row['例文 (Example)']
                            })
                        
                        st.session_state.test_mode = {
                            'started': True,
                            'current_q_idx': 0,
                            'questions': questions,
                            'answers': [None] * len(questions),
                            'score': 0,
                            'detailed_results': [],
                            'selected_category': selected_category,
                            'test_type': test_type,
                            'question_source': 'selected_category' if selected_category != '全カテゴリ' else 'all_random'
                        }
                        st.rerun()

        elif st.session_state.test_mode['started'] == True:
            current_q_idx = st.session_state.test_mode['current_q_idx']
            questions = st.session_state.test_mode['questions']
            
            if current_q_idx < len(questions):
                # 問題表示
                st.subheader(f"質問 {current_q_idx + 1} / {len(questions)}")
                current_question = questions[current_q_idx]
                st.write(current_question['question_text'])
                
                # 回答選択
                user_answer = st.radio(
                    "あなたの回答",
                    current_question['choices'],
                    key=f"q_{current_q_idx}"
                )
                
                col1, col2 = st.columns([1,1])
                with col1:
                    if st.button("前の質問へ", disabled=(current_q_idx == 0)):
                        st.session_state.test_mode['answers'][current_q_idx] = user_answer
                        st.session_state.test_mode['current_q_idx'] -= 1
                        st.rerun()
                with col2:
                    if st.button("次の質問へ"):
                        st.session_state.test_mode['answers'][current_q_idx] = user_answer
                        st.session_state.test_mode['current_q_idx'] += 1
                        st.rerun()
            else:
                # テスト終了
                st.subheader("テスト結果")

                # --- テスト結果と学習進捗をGASに書き込む関数 ---
                def save_test_results_and_progress():
                    nonlocal current_worksheet_name, test_results_sheet_name # nonlocalキーワードを追加

                    questions_in_session = st.session_state.test_mode['questions']
                    user_answers_in_session = st.session_state.test_mode['answers']
                    
                    final_score = 0
                    current_detailed_results = []
                    updated_vocab_ids = set() # 今回のテストで進捗が更新されたIDを追跡

                    # df_vocabをコピーして操作し、最後に元のdf_vocabに代入する
                    temp_df_vocab = st.session_state.df_vocab.copy()

                    for i, q in enumerate(questions_in_session):
                        user_ans = user_answers_in_session[i]
                        is_correct = (user_ans == q['correct_answer'])
                        if is_correct:
                            final_score += 1
                        
                        current_detailed_results.append({
                            'question_text': q['question_text'],
                            'correct_answer': q['correct_answer'],
                            'user_answer': user_ans if user_ans is not None else "未回答",
                            'is_correct': is_correct,
                            'term_id': str(q.get('term_id')), # 文字列として保存
                            'term_name': q.get('term_name', 'N/A'), 
                            'term_definition': q.get('term_definition', 'N/A'), 
                            'term_example': q.get('term_example', 'N/A') 
                        })

                        # 学習進捗の更新ロジック (temp_df_vocabを更新)
                        # ここでIDの型を確実に合わせる。df_vocabのIDはInt64なので比較対象も整数型に
                        if pd.notna(q.get('term_id')):
                            try:
                                # df_vocabのIDはInt64型なので、int()で変換して比較
                                term_id_val = int(q['term_id']) 
                                original_df_index = temp_df_vocab[temp_df_vocab['ID'] == term_id_val].index
                                
                                if not original_df_index.empty:
                                    row_idx = original_df_index[0]
                                    current_progress = temp_df_vocab.loc[row_idx, '学習進捗 (Progress)']
                                    
                                    if is_correct:
                                        if current_progress == 'Not Started':
                                            temp_df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Learning'
                                        elif current_progress == 'Learning':
                                            temp_df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Mastered'
                                    else: # 不正解の場合、進捗を戻す
                                        if current_progress == 'Mastered':
                                            temp_df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Learning'
                                        elif current_progress == 'Learning':
                                            temp_df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Not Started'
                                    updated_vocab_ids.add(term_id_val)
                            except ValueError:
                                st.warning(f"用語ID '{q.get('term_id')}' の型変換に失敗しました。この用語の進捗は更新されません。")


                    st.session_state.test_mode['score'] = final_score
                    st.session_state.test_mode['detailed_results'] = current_detailed_results
                    
                    test_date_obj = datetime.now()
                    category_used = st.session_state.test_mode['selected_category']
                    if st.session_state.test_mode['question_source'] == 'all_random':
                        category_used = '全カテゴリ'
                    
                    test_type_display = {
                        'term_to_def': '用語→説明',
                        'example_to_term': '例文→用語'
                    }[st.session_state.test_mode['test_type']]

                    new_result_df_row = {
                        'Date': test_date_obj,
                        'Category': category_used,
                        'TestType': test_type_display,
                        'Score': final_score,
                        'TotalQuestions': len(questions_in_session),
                        'Details': current_detailed_results # リストとして直接代入
                    }
                    
                    # DataFrame.append は非推奨なので concat を使用
                    if st.session_state.df_test_results.empty:
                        df_test_results_to_save = pd.DataFrame([new_result_df_row], columns=TEST_RESULTS_HEADERS)
                    else:
                        df_test_results_to_save = pd.concat([st.session_state.df_test_results, pd.DataFrame([new_result_df_row], columns=TEST_RESULTS_HEADERS)], ignore_index=True)

                    # テスト結果を保存
                    write_success_results = write_data_to_gas(df_test_results_to_save, test_results_sheet_name)
                    if write_success_results:
                        st.session_state.df_test_results = df_test_results_to_save # セッション状態を更新
                        st.success("テスト結果が保存されました！「データ管理」から確認できます。")
                    else:
                        st.error("テスト結果の保存に失敗しました。")

                    # 学習進捗を保存
                    if updated_vocab_ids:
                        # テンポラリDataFrameからst.session_state.df_vocabを更新
                        st.session_state.df_vocab = temp_df_vocab 
                        write_success_vocab = write_data_to_gas(st.session_state.df_vocab, current_worksheet_name)
                        if write_success_vocab:
                            st.success("学習進捗が更新されました！")
                        else:
                            st.error("学習進捗の更新に失敗しました。")
                    else:
                        st.info("学習進捗の更新はありませんでした。")

                # 実行と結果表示
                if "test_results_saved" not in st.session_state.test_mode or not st.session_state.test_mode["test_results_saved"]:
                    save_test_results_and_progress()
                    st.session_state.test_mode["test_results_saved"] = True
                
                st.write(f"お疲れ様でした！ あなたの最終スコアは {st.session_state.test_mode['score']} / {len(questions)} です。")
                
                if st.button("テストを終了する"):
                    st.session_state.test_mode = None
                    st.session_state.current_page = "データ管理" # テスト終了後はデータ管理ページへ
                    st.rerun()

# --- フッター ---
st.markdown("---")
st.caption("© 2023 Business Terminology Builder")
