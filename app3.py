import streamlit as st
import pandas as pd
import requests # requestsライブラリを追加
import json
import os

# --- 設定項目 ---
# GAS WebアプリのデプロイURL
GAS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbwro4Xl-tIdlgg5nPhppfGJMYvzdVFUEi5Qf8REWo0eoyL5aCJmtKHOZNjQH7No7llZWQ/exec" # ★★★
# GASで設定したAPIキー
GAS_API_KEY = "my_streamlit_secret_key_123" # ★★★ GASで設定したALLOWED_API_KEYと同じ値を貼り付ける ★★★

# --- Streamlit アプリケーションの開始 ---
st.set_page_config(layout="wide")
st.title("ビジネス用語集ビルダー")

# ユーザー認証の状態を管理するセッションステート
if 'username' not in st.session_state:
    st.session_state.username = None

# --- GAS APIとの連携関数 (変更なし、既存のものを再利用) ---
@st.cache_data(ttl=60)
def load_data_from_gas(sheet_name):
    # ... (前回のload_data_from_gas関数と同じコード) ...
    try:
        params = {'api_key': GAS_API_KEY, 'sheet': sheet_name}
        response = requests.get(GAS_WEBAPP_URL, params=params)
        response.raise_for_status()
        data = response.json()

        if 'error' in data:
            st.error(f"GASからエラーが返されました: {data['error']}")
            st.stop()
        
        df = pd.DataFrame(data['data'])
        expected_cols = ['ID', '用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)', '学習進捗 (Progress)']
        for col in expected_cols:
            if col not in df.columns:
                df[col] = ''
        df = df[expected_cols]
        df = df.dropna(how='all')

        if 'ID' not in df.columns or df['ID'].isnull().all():
            df['ID'] = range(1, len(df) + 1)
        else:
            df['ID'] = pd.to_numeric(df['ID'], errors='coerce').fillna(0).astype(int)
            df = df.sort_values(by='ID').reset_index(drop=True)

        return df
    except requests.exceptions.RequestException as e:
        st.error(f"GAS Webアプリへの接続に失敗しました: {e}")
        st.info(f"GAS WebアプリのURL: {GAS_WEBAPP_URL} が正しいか、デプロイされているか確認してください。")
        st.stop()
    except json.JSONDecodeError:
        st.error("GASからのレスポンスをJSONとして解析できませんでした。GASのコードを確認してください。")
        st.stop()
    except Exception as e:
        st.error(f"データの読み込み中に予期せぬエラーが発生しました: {e}")
        st.stop()

def write_data_to_gas(df, sheet_name):
    # ... (前回のwrite_data_to_gas関数と同じコード) ...
    try:
        data_to_send = [df.columns.tolist()] + df.values.tolist()
        params = {'api_key': GAS_API_KEY, 'sheet': sheet_name}
        headers = {'Content-Type': 'application/json'}
        response = requests.post(GAS_WEBAPP_URL, params=params, headers=headers, json={'data': data_to_send})
        response.raise_for_status()
        result = response.json()

        if 'error' in result:
            st.error(f"GAS書き込み中にエラーが返されました: {result['error']}")
            return False
        
        st.success(f"データがスプレッドシート '{sheet_name}' に保存されました！")
        st.cache_data.clear()
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"GAS Webアプリへの書き込み接続に失敗しました: {e}")
        st.info(f"GAS WebアプリのURL: {GAS_WEBAPP_URL} が正しいか、デプロイされているか確認してください。")
        return False
    except json.JSONDecodeError:
        st.error("GASからのレスポンスをJSONとして解析できませんでした。GASのコードを確認してください。")
        return False
    except Exception as e:
        st.error(f"データの書き込み中に予期せぬエラーが発生しました: {e}")
        return False

# --- ユーザー名入力処理 ---
if st.session_state.username is None:
    st.info("最初にあなたの名前を入力してください。")
    with st.form("username_form"):
        input_username = st.text_input("あなたの名前を入力してください")
        submit_username = st.form_submit_button("進む")
        if submit_username and input_username:
            st.session_state.username = input_username
            st.rerun()

# --- ユーザーログイン後のメインコンテンツ ---
if st.session_state.username:
    st.sidebar.write(f"ようこそ、**{st.session_state.username}** さん！")
    
    sanitized_username = "".join(filter(str.isalnum, st.session_state.username))
    current_worksheet_name = f"Sheet_{sanitized_username}"

    df_vocab = load_data_from_gas(current_worksheet_name)

    # セッションステートの初期化（テストモード用）
    if 'test_mode' not in st.session_state:
        st.session_state.test_mode = {
            'type': None, # 'term_to_def' or 'example_to_term'
            'current_question': None,
            'current_answer': None,
            'choices': [],
            'score': 0,
            'total_questions': 0,
            'answered': False
        }

    # --- テスト問題生成ヘルパー関数 ---
    def generate_question(test_type, vocab_df):
        if vocab_df.empty or len(vocab_df) < 1:
            return None # 問題を生成できない
        
        # 出題対象の用語をランダムに選択
        question_term_row = vocab_df.sample(n=1).iloc[0]
        
        correct_answer = ""
        question_text = ""
        all_options_pool = [] # 不正解の選択肢の候補

        if test_type == 'term_to_def':
            question_text = question_term_row['用語 (Term)']
            correct_answer = question_term_row['説明 (Definition)']
            all_options_pool = vocab_df['説明 (Definition)'].tolist()
        elif test_type == 'example_to_term':
            if pd.isna(question_term_row['例文 (Example)']) or question_term_row['例文 (Example)'] == '':
                return generate_question(test_type, vocab_df) # 例文がない場合は再試行
            question_text = question_term_row['例文 (Example)']
            correct_answer = question_term_row['用語 (Term)']
            all_options_pool = vocab_df['用語 (Term)'].tolist()
        
        # 不正解の選択肢を選ぶ（最大3つ）
        incorrect_choices = []
        possible_incorrects = [opt for opt in all_options_pool if opt != correct_answer]
        if len(possible_incorrects) > 3:
            incorrect_choices = random.sample(possible_incorrects, 3)
        else:
            incorrect_choices = possible_incorrects # 3つ未満なら全て使用

        choices = [correct_answer] + incorrect_choices
        random.shuffle(choices) # 選択肢をランダムにシャッフル

        return {
            'question_text': question_text,
            'correct_answer': correct_answer,
            'choices': choices,
            'question_id': question_term_row['ID'] # 学習進捗更新用にIDを保存
        }

    # --- テストモードの開始・リセット ---
    def start_new_test(test_type):
        st.session_state.test_mode['type'] = test_type
        st.session_state.test_mode['score'] = 0
        st.session_state.test_mode['total_questions'] = 0
        st.session_state.test_mode['answered'] = False
        st.session_state.test_mode['current_question'] = None # 次の問題生成を促す
        st.session_state.current_answer_selection = None # ラジオボタンの選択をリセット
        generate_next_question()

    def generate_next_question():
        st.session_state.test_mode['current_question'] = generate_question(st.session_state.test_mode['type'], df_vocab)
        st.session_state.test_mode['current_answer'] = None
        st.session_state.test_mode['choices'] = st.session_state.test_mode['current_question']['choices'] if st.session_state.test_mode['current_question'] else []
        st.session_state.test_mode['answered'] = False
        st.session_state.current_answer_selection = None # ラジオボタンの選択をリセット


    # --- ナビゲーション ---
    st.sidebar.header("ナビゲーション")
    page = st.sidebar.radio("Go to", ["用語一覧", "用語の追加・編集", "テストモード", "データ管理"])

    if page == "用語一覧":
        st.header("登録済みビジネス用語")
        # ... (前回の用語一覧のコードと同じ) ...
        if not df_vocab.empty:
            all_categories = ['全てのカテゴリ'] + sorted(df_vocab['カテゴリ (Category)'].dropna().unique().tolist())
            selected_category = st.selectbox("カテゴリで絞り込む:", all_categories)
            filtered_df = df_vocab.copy()
            if selected_category != '全てのカテゴリ':
                filtered_df = filtered_df[filtered_df['カテゴリ (Category)'] == selected_category]
            search_term = st.text_input("用語や説明を検索:")
            if search_term:
                filtered_df = filtered_df[
                    filtered_df.apply(lambda row: search_term.lower() in str(row).lower(), axis=1)
                ]
            st.dataframe(filtered_df, use_container_width=True, hide_index=True)
        else:
            st.info("まだ用語が登録されていません。「用語の追加・編集」から追加してください。")

    elif page == "用語の追加・編集":
        # ... (前回の用語の追加・編集のコードと同じ) ...
        st.header("新しい用語の追加")
        with st.form("add_term_form"):
            new_term = st.text_input("用語 (Term)*", help="例: Burn Rate")
            new_definition = st.text_area("説明 (Definition)*", help="例: キャッシュを消費する速度。通常、月単位で測定される。")
            new_example = st.text_area("例文 (Example)", help="例: 「スタートアップは高いBurn Rateを維持しているため、追加の資金調達が必要だ。」")
            existing_categories = sorted(df_vocab['カテゴリ (Category)'].dropna().unique().tolist())
            selected_category = st.selectbox("カテゴリ (Category)", 
                                             options=['新しいカテゴリを作成'] + existing_categories)
            if selected_category == '新しいカテゴリを作成':
                new_category = st.text_input("新しいカテゴリ名を入力してください")
                category_to_add = new_category
            else:
                category_to_add = selected_category
            submitted = st.form_submit_button("用語を追加")
            if submitted:
                if new_term and new_definition and category_to_add:
                    new_id = 1 if df_vocab.empty else df_vocab['ID'].max() + 1
                    new_row = pd.DataFrame([{
                        'ID': new_id,
                        '用語 (Term)': new_term,
                        '説明 (Definition)': new_definition,
                        '例文 (Example)': new_example,
                        'カテゴリ (Category)': category_to_add,
                        '学習進捗 (Progress)': 'Not Started'
                    }])
                    updated_df = pd.concat([df_vocab, new_row], ignore_index=True)
                    if write_data_to_gas(updated_df, current_worksheet_name):
                        st.success(f"用語 '{new_term}' が追加されました！")
                        st.rerun()
                else:
                    st.error("用語、説明、カテゴリは必須項目です。")
        st.markdown("---")
        st.header("既存用語の編集・削除")
        if not df_vocab.empty:
            term_to_edit_delete = st.selectbox("編集または削除する用語を選択:", 
                                                options=['選択してください'] + sorted(df_vocab['用語 (Term)'].tolist()))
            if term_to_edit_delete != '選択してください':
                selected_term_data = df_vocab[df_vocab['用語 (Term)'] == term_to_edit_delete].iloc[0]
                with st.form("edit_delete_form"):
                    edited_term = st.text_input("用語 (Term)*", value=selected_term_data['用語 (Term)'])
                    edited_definition = st.text_area("説明 (Definition)*", value=selected_term_data['説明 (Definition)'])
                    edited_example = st.text_area("例文 (Example)", value=selected_term_data['例文 (Example)'])
                    existing_categories_for_edit = sorted(df_vocab['カテゴリ (Category)'].dropna().unique().tolist())
                    try:
                        current_category_index = existing_categories_for_edit.index(selected_term_data['カテゴリ (Category)'])
                        default_index_for_selectbox = current_category_index + 1
                    except ValueError:
                        default_index_for_selectbox = 0
                    edited_selected_category = st.selectbox("カテゴリ (Category)", 
                                                            options=['新しいカテゴリを作成'] + existing_categories_for_edit,
                                                            index=default_index_for_selectbox) 
                    edited_new_category = ""
                    if edited_selected_category == '新しいカテゴリを作成':
                        edited_new_category = st.text_input("新しいカテゴリ名を入力してください", value="")
                        category_to_save = edited_new_category
                    else:
                        category_to_save = edited_selected_category
                    edited_progress = st.selectbox("学習進捗 (Progress)", 
                                                   options=['Not Started', 'Learning', 'Mastered'],
                                                   index=['Not Started', 'Learning', 'Mastered'].index(selected_term_data['学習進捗 (Progress)']))
                    col_edit, col_delete = st.columns(2)
                    edit_submitted = col_edit.form_submit_button("更新")
                    delete_submitted = col_delete.form_submit_button("削除")
                    if edit_submitted:
                        if edited_term and edited_definition and category_to_save:
                            idx = df_vocab[df_vocab['ID'] == selected_term_data['ID']].index[0]
                            df_vocab.loc[idx, '用語 (Term)'] = edited_term
                            df_vocab.loc[idx, '説明 (Definition)'] = edited_definition
                            df_vocab.loc[idx, '例文 (Example)'] = edited_example
                            df_vocab.loc[idx, 'カテゴリ (Category)'] = category_to_save
                            df_vocab.loc[idx, '学習進捗 (Progress)'] = edited_progress
                            if write_data_to_gas(df_vocab, current_worksheet_name):
                                st.success(f"用語 '{edited_term}' が更新されました！")
                                st.rerun()
                        else:
                            st.error("用語、説明、カテゴリは必須項目です。")
                    if delete_submitted:
                        df_vocab = df_vocab[df_vocab['ID'] != selected_term_data['ID']]
                        if write_data_to_gas(df_vocab, current_worksheet_name):
                            st.warning(f"用語 '{selected_term_data['用語 (Term)']}' が削除されました。")
                            st.rerun()
        else:
            st.info("編集・削除できる用語がありません。")

    elif page == "テストモード":
        st.header("テストモード")

        if df_vocab.empty or len(df_vocab) < 4: # 少なくとも4つの用語がないと選択肢が作れない
            st.warning("テストを開始するには、少なくとも4つ以上の用語を登録してください。")
            st.stop()
        
        # テスト形式の選択
        test_type_selection = st.radio("テスト形式を選択してください:", 
                                       ["用語から説明を選択", "例文から用語を選択"],
                                       key="test_type_selector")

        selected_test_type = ''
        if test_type_selection == "用語から説明を選択":
            selected_test_type = 'term_to_def'
        else:
            selected_test_type = 'example_to_term'

        if st.session_state.test_mode['type'] != selected_test_type or st.sidebar.button("テストをやり直す", key="reset_test_button"):
            start_new_test(selected_test_type)
            st.rerun()

        # 現在の問題を生成または表示
        if st.session_state.test_mode['current_question'] is None:
            generate_next_question()
            st.rerun() # 問題生成後、再描画して表示

        current_q = st.session_state.test_mode['current_question']
        if current_q is None:
            st.error("問題の生成に失敗しました。適切なデータが登録されているか確認してください。")
            st.stop()
        
        st.subheader(f"問題 {st.session_state.test_mode['total_questions'] + 1}")
        
        if st.session_state.test_mode['type'] == 'term_to_def':
            st.write(f"### 用語: **{current_q['question_text']}**")
            st.write("正しい説明を選択してください。")
        elif st.session_state.test_mode['type'] == 'example_to_term':
            st.write(f"### 例文: **{current_q['question_text']}**")
            st.write("正しい用語を選択してください。")
        
        st.session_state.current_answer_selection = st.radio("選択肢:", current_q['choices'], 
                                                            index=None, # デフォルトで何も選択されていない状態
                                                            disabled=st.session_state.test_mode['answered'],
                                                            key=f"q_{st.session_state.test_mode['total_questions']}")
        
        col1, col2 = st.columns(2)

        with col1:
            if st.button("回答する", disabled=st.session_state.test_mode['answered'] or st.session_state.current_answer_selection is None):
                st.session_state.test_mode['answered'] = True
                st.session_state.test_mode['total_questions'] += 1
                selected_answer = st.session_state.current_answer_selection

                if selected_answer == current_q['correct_answer']:
                    st.success("正解です！ 🎉")
                    st.session_state.test_mode['score'] += 1
                    # 学習進捗を更新 (任意)
                    st.toast("学習進捗を更新しました！")
                    idx = df_vocab[df_vocab['ID'] == current_q['question_id']].index[0]
                    current_progress = df_vocab.loc[idx, '学習進捗 (Progress)']
                    if current_progress == 'Not Started':
                        df_vocab.loc[idx, '学習進捗 (Progress)'] = 'Learning'
                    elif current_progress == 'Learning':
                        df_vocab.loc[idx, '学習進捗 (Progress)'] = 'Mastered'
                    write_data_to_gas(df_vocab, current_worksheet_name)
                else:
                    st.error(f"不正解です。😫 正解は: **{current_q['correct_answer']}** でした。")
                    # 学習進捗を更新 (任意)
                    st.toast("学習進捗を更新しました！")
                    idx = df_vocab[df_vocab['ID'] == current_q['question_id']].index[0]
                    df_vocab.loc[idx, '学習進捗 (Progress)'] = 'Learning' # 不正解の場合はLearningに戻す
                    write_data_to_gas(df_vocab, current_worksheet_name)
                st.rerun() # 回答後に再描画して結果と次のボタンを表示
        
        with col2:
            if st.session_state.test_mode['answered']:
                if st.button("次の問題へ", key="next_question_button"):
                    generate_next_question()
                    st.rerun()
            
        st.markdown("---")
        st.metric(label="現在のスコア", value=f"{st.session_state.test_mode['score']} / {st.session_state.test_mode['total_questions']}")

    elif page == "データ管理":
        st.header("データ管理")
        st.subheader("学習進捗のリセット")
        st.warning(f"**{st.session_state.username}** さんの学習進捗を全てリセットします。この操作は元に戻せません。")
        
        if st.button("学習進捗をリセットする"):
            if not df_vocab.empty:
                df_vocab['学習進捗 (Progress)'] = 'Not Started'
                if write_data_to_gas(df_vocab, current_worksheet_name):
                    st.success("学習進捗がリセットされました！")
                    st.rerun()
            else:
                st.info("リセットする学習データがありません。")

else:
    st.empty()