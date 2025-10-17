import streamlit as st
import pandas as pd
import requests
import json
import os
import random
from datetime import datetime

# --- 設定項目 ---
GAS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbzIHJdzrPWRgu3uyOb2A1rHQTvpxzU6sLKBm5Ybwt--ozxLFe0_i7nr071RjwjgdkaxGA/exec" 
GAS_API_KEY = "my_streamlit_secret_key_123" 

# --- Streamlit アプリケーションの開始 ---
st.set_page_config(layout="wide")
st.title("ビジネス用語集ビルダー")

if 'username' not in st.session_state:
    st.session_state.username = None

# --- GAS APIとの連携関数 ---
@st.cache_data(ttl=60)
def load_data_from_gas(sheet_name):
    try:
        params = {'api_key': GAS_API_KEY, 'sheet': sheet_name, 'action': 'read_data'}
        response = requests.get(GAS_WEBAPP_URL, params=params)
        response.raise_for_status() # HTTPエラーが発生した場合に例外を発生させる

        data = response.json()

        if 'error' in data:
            # GASが「シートが見つかりません」という特定のエラーを返した場合、空のDataFrameを返す
            if "シートが見つかりません" in data['error'] or "Sheet not found" in data['error']:
                st.info(f"スプレッドシートに '{sheet_name}' が見つかりませんでした。新しく作成されます。")
                if sheet_name.startswith("Sheet_TestResults_"):
                    return pd.DataFrame(columns=['Date', 'Category', 'TestType', 'Score', 'TotalQuestions', 'Details'])
                else:
                    return pd.DataFrame(columns=['ID', '用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)', '学習進捗 (Progress)'])
            else:
                # その他のGASからのエラーは通常のエラーとして処理
                st.error(f"GASからエラーが返されました: {data['error']}")
                st.stop()
        
        df = pd.DataFrame(data['data'])
        
        if not sheet_name.startswith("Sheet_TestResults_"):
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
        else: # テスト結果シートの場合
            if 'Date' in df.columns and not df['Date'].empty:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                df = df.dropna(subset=['Date']) 
                if not df.empty:
                    df = df.sort_values(by='Date', ascending=False).reset_index(drop=True)
            else:
                if df.empty:
                    return pd.DataFrame(columns=['Date', 'Category', 'TestType', 'Score', 'TotalQuestions', 'Details'])
                else:
                    # 'Date'カラムがないか空の場合も、DataFrame自体は返す
                    st.warning(f"テスト結果シート '{sheet_name}' に 'Date' カラムが見つからないか空です。")
                    return df 

        return df
    except requests.exceptions.HTTPError as e:
        # HTTP 500などのサーバーエラーはこちらで捕捉
        st.error(f"GAS Webアプリへの接続に失敗しました: {e}")
        st.info(f"GAS WebアプリのURL: {GAS_WEBAPP_URL} が正しいか、デプロイされているか、またはGAS側のスクリプトにエラーがないか確認してください。")
        st.stop()
    except requests.exceptions.RequestException as e:
        st.error(f"GAS Webアプリへの接続に失敗しました: {e}")
        st.info(f"GAS WebアプリのURL: {GAS_WEBAPP_URL} が正しいか、デプロイされているか確認してください。")
        st.stop()
    except json.JSONDecodeError:
        st.error(f"GASからのレスポンスをJSONとして解析できませんでした。レスポンス内容: {response.text}。GASのコードを確認してください。")
        st.stop()
    except Exception as e:
        st.error(f"データの読み込み中に予期せぬエラーが発生しました: {e}")
        st.stop()

def write_data_to_gas(df, sheet_name):
    try:
        if 'Date' in df.columns and pd.api.types.is_datetime64_any_dtype(df['Date']):
            df_to_send = df.copy()
            df_to_send['Date'] = df_to_send['Date'].dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            df_to_send = df.copy()
            
        data_to_send = [df_to_send.columns.tolist()] + df_to_send.values.tolist()
        params = {'api_key': GAS_API_KEY, 'sheet': sheet_name, 'action': 'write_data'}
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
        st.error(f"GASからのレスポンスをJSONとして解析できませんでした。レスポンス内容: {response.text}。GASのコードを確認してください。")
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
    
    # ユーザー名からシート名を生成
    sanitized_username = "".join(filter(str.isalnum, st.session_state.username))
    current_worksheet_name = f"Sheet_{sanitized_username}"
    test_results_sheet_name = f"Sheet_TestResults_{sanitized_username}"

    # ユーザーの用語データをロード
    df_vocab = load_data_from_gas(current_worksheet_name)
    df_test_results = load_data_from_gas(test_results_sheet_name) 

    # セッションステートの初期化（テストモード用）
    if 'test_mode' not in st.session_state:
        st.session_state.test_mode = {
            'is_active': False,
            'test_type': None, # 'term_to_def' or 'example_to_term'
            'question_source': None, # 'category' or 'all_random'
            'selected_category': '全てのカテゴリ',
            'questions': [], # 出題される全問題リスト
            'current_question_index': 0, # 現在表示中の問題インデックス
            'score': 0, # 正解数
            'answers': [], # 各問題のユーザーの回答を保存 (Noneまたは選択肢文字列)
            'detailed_results': [] # 各問題の詳細結果（問題文、正解、ユーザー回答、正誤）
        }
    
    # セッションステートの初期化（学習モード用）
    if 'learning_mode' not in st.session_state:
        st.session_state.learning_mode = {
            'filtered_df_indices': [],
            'current_index_in_filtered': 0,
            'selected_category': '全てのカテゴリ',
            'progress_filter': '全ての進捗'
        }

    # セッションステートの初期化（辞書モード用）
    if 'dictionary_mode' not in st.session_state:
        st.session_state.dictionary_mode = {
            'search_term': '',
            'selected_category': '全てのカテゴリ',
            'expanded_term_id': None # 展開表示する用語のID
        }


    # --- テスト問題生成ヘルパー関数 ---
    def generate_questions_for_test(test_type, question_source, category_filter='全てのカテゴリ', num_questions=10):
        eligible_vocab_df = df_vocab.copy()

        if question_source == 'category' and category_filter != '全てのカテゴリ':
            eligible_vocab_df = eligible_vocab_df[eligible_vocab_df['カテゴリ (Category)'] == category_filter]
        
        if test_type == 'example_to_term':
            eligible_vocab_df = eligible_vocab_df[pd.notna(eligible_vocab_df['例文 (Example)']) & (eligible_vocab_df['例文 (Example)'] != '')]

        if eligible_vocab_df.empty or len(eligible_vocab_df) < num_questions:
            return None 
        
        selected_terms = eligible_vocab_df.sample(n=num_questions, replace=False)
        
        questions_list = []
        for _, question_term_row in selected_terms.iterrows():
            correct_answer = ""
            question_text = ""
            all_options_pool = []

            if test_type == 'term_to_def':
                question_text = question_term_row['用語 (Term)']
                correct_answer = question_term_row['説明 (Definition)']
                all_options_pool = eligible_vocab_df['説明 (Definition)'].tolist()
            elif test_type == 'example_to_term':
                question_text = question_term_row['例文 (Example)']
                correct_answer = question_term_row['用語 (Term)']
                all_options_pool = eligible_vocab_df['用語 (Term)'].tolist()
            
            incorrect_choices = []
            possible_incorrects = [opt for opt in all_options_pool if opt != correct_answer]
            
            if len(possible_incorrects) >= 3:
                incorrect_choices = random.sample(possible_incorrects, 3)
            else:
                incorrect_choices = possible_incorrects
            
            choices = [correct_answer] + incorrect_choices
            random.shuffle(choices)

            questions_list.append({
                'question_text': question_text,
                'correct_answer': correct_answer,
                'choices': choices,
                'term_id': question_term_row['ID'],
                'term_name': question_term_row['用語 (Term)'],
                'term_definition': question_term_row['説明 (Definition)'], 
                'term_example': question_term_row['例文 (Example)'] 
            })
        return questions_list

    # --- テストモードの開始・リセット ---
    def start_new_test(test_type, question_source, category_filter):
        st.session_state.test_mode['is_active'] = True
        st.session_state.test_mode['test_type'] = test_type
        st.session_state.test_mode['question_source'] = question_source
        st.session_state.test_mode['selected_category'] = category_filter
        st.session_state.test_mode['questions'] = generate_questions_for_test(test_type, question_source, category_filter, num_questions=10)
        st.session_state.test_mode['current_question_index'] = 0 
        st.session_state.test_mode['score'] = 0
        st.session_state.test_mode['answers'] = [None] * len(st.session_state.test_mode['questions']) if st.session_state.test_mode['questions'] else []
        st.session_state.test_mode['detailed_results'] = []
        
        if st.session_state.test_mode['questions'] is None or not st.session_state.test_mode['questions']:
            st.error("テスト問題を作成できませんでした。出題条件を満たす用語が不足している可能性があります。")
            st.session_state.test_mode['is_active'] = False
        st.rerun()

    # --- テストモードの再開 ---
    def resume_test():
        st.session_state.test_mode['is_active'] = True
        st.rerun()

    # --- ナビゲーション ---
    st.sidebar.header("ナビゲーション")
    page = st.sidebar.radio("Go to", [
        "学習モード",
        "テストモード",
        "辞書モード",
        "用語一覧", 
        "用語の追加・編集", 
        "データ管理"
    ])

    if page == "用語一覧":
        st.header("登録済みビジネス用語")
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

    elif page == "学習モード":
        st.header("学習モード")

        if df_vocab.empty:
            st.info("学習する用語がありません。「用語の追加・編集」から追加してください。")
            st.stop()
        
        all_categories = ['全てのカテゴリ'] + sorted(df_vocab['カテゴリ (Category)'].dropna().unique().tolist())
        progress_options = ['全ての進捗', 'Not Started', 'Learning', 'Mastered']

        col_filter1, col_filter2 = st.columns(2)
        with col_filter1:
            selected_category_filter = st.selectbox("カテゴリで絞り込む:", all_categories, 
                                                    key="learn_category_filter",
                                                    index=all_categories.index(st.session_state.learning_mode['selected_category']))
        with col_filter2:
            selected_progress_filter = st.selectbox("学習進捗で絞り込む:", progress_options,
                                                    key="learn_progress_filter",
                                                    index=progress_options.index(st.session_state.learning_mode['progress_filter']))
        
        # まずfiltered_dfを定義
        filtered_df = df_vocab.copy()
        if selected_category_filter != '全てのカテゴリ':
            filtered_df = filtered_df[filtered_df['カテゴリ (Category)'] == selected_category_filter]
        if selected_progress_filter != '全ての進捗':
            filtered_df = filtered_df[filtered_df['学習進捗 (Progress)'] == selected_progress_filter]

        # フィルタリング条件が変わったか、または filtered_df_indices が初期化されていないかチェック
        if (selected_category_filter != st.session_state.learning_mode['selected_category'] or
            selected_progress_filter != st.session_state.learning_mode['progress_filter'] or
            not st.session_state.learning_mode['filtered_df_indices'] or
            # 現在のフィルタリング結果のインデックスとセッションステートのインデックスが異なるかチェック
            set(st.session_state.learning_mode['filtered_df_indices']) != set(filtered_df.index.tolist())
            ):
            st.session_state.learning_mode['selected_category'] = selected_category_filter
            st.session_state.learning_mode['progress_filter'] = selected_progress_filter
            st.session_state.learning_mode['filtered_df_indices'] = filtered_df.index.tolist()
            st.session_state.learning_mode['current_index_in_filtered'] = 0
            if not filtered_df.empty: # フィルタリング結果が空でない場合のみrerun
                st.rerun()

        # filtered_dfが空だった場合の処理
        if filtered_df.empty:
            st.info("この条件に一致する用語は見つかりませんでした。")
            st.session_state.learning_mode['filtered_df_indices'] = []
            st.session_state.learning_mode['current_index_in_filtered'] = 0
            st.stop()
        
        total_terms_in_filtered = len(filtered_df)
        current_display_index_in_filtered = st.session_state.learning_mode['current_index_in_filtered']

        # 現在のインデックスが範囲外にならないように調整 (フィルタリング結果が変わった場合など)
        if not st.session_state.learning_mode['filtered_df_indices'] or \
           current_display_index_in_filtered >= len(st.session_state.learning_mode['filtered_df_indices']):
            st.session_state.learning_mode['current_index_in_filtered'] = 0
            current_display_index_in_filtered = 0 # 再度設定
            st.rerun() # リセットして再描画

        original_idx = st.session_state.learning_mode['filtered_df_indices'][current_display_index_in_filtered]
        current_term_data = df_vocab.loc[original_idx]

        st.markdown("---")
        st.subheader(f"現在表示中: {current_display_index_in_filtered + 1} / {total_terms_in_filtered}")

        st.metric("用語", current_term_data['用語 (Term)'])
        st.info(f"カテゴリ: **{current_term_data['カテゴリ (Category)']}**")
        st.write(f"### 説明")
        st.markdown(f"**{current_term_data['説明 (Definition)']}**")
        if pd.notna(current_term_data['例文 (Example)']) and current_term_data['例文 (Example)'] != '':
            st.write(f"### 例文")
            st.markdown(f"*{current_term_data['例文 (Example)']}*")
        
        st.write(f"---")
        
        st.write(f"現在の学習進捗: **{current_term_data['学習進捗 (Progress)']}**")
        
        # 学習進捗の更新セレクトボックスを完全に削除

        st.markdown("---")

        col_prev, col_random, col_next = st.columns(3)
        with col_prev:
            if st.button("前の用語へ", disabled=(current_display_index_in_filtered == 0)):
                st.session_state.learning_mode['current_index_in_filtered'] -= 1
                st.rerun()
        with col_random:
            if st.button("ランダムな用語へ"):
                st.session_state.learning_mode['current_index_in_filtered'] = random.randrange(total_terms_in_filtered)
                st.rerun()
        with col_next:
            if st.button("次の用語へ", disabled=(current_display_index_in_filtered >= total_terms_in_filtered - 1)):
                st.session_state.learning_mode['current_index_in_filtered'] += 1
                st.rerun()

    elif page == "辞書モード":
        st.header("辞書モード")

        if df_vocab.empty:
            st.info("辞書に登録された用語がありません。「用語の追加・編集」から追加してください。")
            st.stop()
        
        all_categories = ['全てのカテゴリ'] + sorted(df_vocab['カテゴリ (Category)'].dropna().unique().tolist())

        search_col, category_col = st.columns([2, 1])
        with search_col:
            st.session_state.dictionary_mode['search_term'] = st.text_input("用語や説明を検索:", 
                                                                             value=st.session_state.dictionary_mode['search_term'],
                                                                             key="dict_search_input")
        with category_col:
            st.session_state.dictionary_mode['selected_category'] = st.selectbox("カテゴリで絞り込む:", all_categories,
                                                                                 index=all_categories.index(st.session_state.dictionary_mode['selected_category']),
                                                                                 key="dict_category_filter")

        filtered_df = df_vocab.copy()
        
        if st.session_state.dictionary_mode['selected_category'] != '全てのカテゴリ':
            filtered_df = filtered_df[filtered_df['カテゴリ (Category)'] == st.session_state.dictionary_mode['selected_category']]
        
        if st.session_state.dictionary_mode['search_term']:
            search_lower = st.session_state.dictionary_mode['search_term'].lower()
            filtered_df = filtered_df[
                filtered_df.apply(lambda row: 
                                  search_lower in str(row['用語 (Term)']).lower() or
                                  search_lower in str(row['説明 (Definition)']).lower() or
                                  (pd.notna(row['例文 (Example)']) and search_lower in str(row['例文 (Example)']).lower()), 
                                  axis=1)
            ]
        
        if filtered_df.empty:
            st.info("この条件に一致する用語は見つかりませんでした。")
        else:
            st.markdown("---")
            st.subheader(f"検索結果 ({len(filtered_df)} 件)")
            for _, row in filtered_df.iterrows():
                is_expanded = (st.session_state.dictionary_mode['expanded_term_id'] == row['ID'])
                with st.expander(f"**{row['用語 (Term)']}.** （カテゴリ: {row['カテゴリ (Category)']}）", 
                                  expanded=is_expanded):
                    st.write(f"### 説明")
                    st.markdown(f"**{row['説明 (Definition)']}**")
                    if pd.notna(row['例文 (Example)']) and row['例文 (Example)'] != '':
                        st.write(f"### 例文")
                        st.markdown(f"*{row['例文 (Example)']}*")
                    
                    if is_expanded:
                        if st.button("閉じる", key=f"close_{row['ID']}"):
                            st.session_state.dictionary_mode['expanded_term_id'] = None
                            st.rerun()
                    else:
                        if st.button("詳細を見る", key=f"open_{row['ID']}"):
                            st.session_state.dictionary_mode['expanded_term_id'] = row['ID']
                            st.rerun()
                st.markdown("---") 

    elif page == "テストモード":
        st.header("テストモード")
        if df_vocab.empty:
            st.info("テストする用語がありません。「用語の追加・編集」から追加してください。")
            st.stop()

        all_categories_for_test = ['全てのカテゴリ'] + sorted(df_vocab['カテゴリ (Category)'].dropna().unique().tolist())
        
        # テストがアクティブでない場合 (テスト設定画面)
        if not st.session_state.test_mode['is_active']:
            # 中断中のテストがあるかチェック
            if st.session_state.test_mode['questions'] and st.session_state.test_mode['current_question_index'] < len(st.session_state.test_mode['questions']):
                st.warning("中断中のテストがあります。")
                if st.button("テストを再開", key="resume_test_button"):
                    resume_test()
                    st.stop() 

            st.subheader("新しいテストを開始")
            test_type_selection = st.radio("テストタイプ:", 
                                           options=['用語 → 説明テスト', '例文 → 用語テスト'],
                                           key="test_type_select")
            
            st.subheader("出題形式を選択してください")
            question_source_selection = st.radio("問題ソース:", 
                                                  options=['カテゴリからランダム10問', '全用語からランダム10問'],
                                                  key="question_source_select")
            
            selected_category_for_test = '全てのカテゴリ'
            if question_source_selection == 'カテゴリからランダム10問':
                selected_category_for_test = st.selectbox("カテゴリを選択:", all_categories_for_test,
                                                        key="test_category_filter")

            start_test_button = st.button("テスト開始")

            if start_test_button:
                test_type_map = {'用語 → 説明テスト': 'term_to_def', '例文 → 用語テスト': 'example_to_term'}
                question_source_map = {'カテゴリからランダム10問': 'category', '全用語からランダム10問': 'all_random'}
                
                start_new_test(test_type_map[test_type_selection], 
                               question_source_map[question_source_selection], 
                               selected_category_for_test)
        
        # テストがアクティブな場合 (問題出題画面)
        else:
            questions = st.session_state.test_mode['questions']
            current_idx = st.session_state.test_mode['current_question_index']
            total_questions = len(questions)

            # 問題が生成されなかった場合
            if not questions:
                st.error("この条件でテスト問題を作成できませんでした。用語の数や例文の有無を確認してください。")
                if st.button("テストを終了する", key="end_test_no_q"):
                    st.session_state.test_mode['is_active'] = False
                    st.session_state.test_mode['questions'] = [] 
                    st.session_state.test_mode['current_question_index'] = 0
                    st.session_state.test_mode['answers'] = []
                    st.session_state.test_mode['detailed_results'] = []
                    st.rerun()
                st.stop()

            # テスト完了後の結果表示
            if current_idx >= total_questions:
                st.subheader("テスト結果")
                
                final_score = 0
                st.session_state.test_mode['detailed_results'] = []
                for i, q in enumerate(questions):
                    user_ans = st.session_state.test_mode['answers'][i]
                    is_correct = (user_ans == q['correct_answer'])
                    if is_correct:
                        final_score += 1
                    
                    st.session_state.test_mode['detailed_results'].append({
                        'question_text': q['question_text'],
                        'correct_answer': q['correct_answer'],
                        'user_answer': user_ans if user_ans is not None else "未回答",
                        'is_correct': is_correct,
                        'term_name': q.get('term_name', 'N/A'), # .get() を使用して KeyError を回避
                        'term_definition': q.get('term_definition', 'N/A'), # .get() を使用して KeyError を回避
                        'term_example': q.get('term_example', 'N/A') # .get() を使用して KeyError を回避
                    })
                
                st.session_state.test_mode['score'] = final_score 
                
                st.write(f"お疲れ様でした！あなたの最終スコアは **{final_score} / {total_questions}** です。")
                
                test_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                category_used = st.session_state.test_mode['selected_category']
                if st.session_state.test_mode['question_source'] == 'all_random':
                    category_used = '全カテゴリ' 
                
                test_type_display = {
                    'term_to_def': '用語→説明',
                    'example_to_term': '例文→用語'
                }[st.session_state.test_mode['test_type']]

                # JSONシリアライズ可能にするために、詳細結果をコピーして辞書に変換
                # PandasのNaN値をNoneに変換することで、JSONシリアライズエラーを回避
                serializable_details = []
                for detail_item in st.session_state.test_mode['detailed_results']:
                    serializable_item = {k: (None if pd.isna(v) else v) for k, v in detail_item.items()}
                    serializable_details.append(serializable_item)

                test_details_str = json.dumps(serializable_details, ensure_ascii=False)

                new_result = pd.DataFrame([{
                    'Date': test_date,
                    'Category': category_used,
                    'TestType': test_type_display,
                    'Score': final_score,
                    'TotalQuestions': total_questions,
                    'Details': test_details_str
                }])
                
                if df_test_results.empty:
                    df_test_results = pd.DataFrame(columns=['Date', 'Category', 'TestType', 'Score', 'TotalQuestions', 'Details'])

                updated_df_test_results = pd.concat([df_test_results, new_result], ignore_index=True)
                
                if write_data_to_gas(updated_df_test_results, test_results_sheet_name):
                    st.success("テスト結果が保存されました！「データ管理」から確認できます。")
                
                st.markdown("---")
                st.subheader("詳細結果")
                for i, detail in enumerate(st.session_state.test_mode['detailed_results']):
                    is_correct_icon = "✅" if detail['is_correct'] else "❌"
                    st.write(f"**問題 {i+1}** {is_correct_icon}")
                    st.write(f"　- 正解: {detail['correct_answer']}")
                    st.write(f"　- あなたの回答: {detail.get('user_answer', 'N/A')}")
                    st.write("---辞書情報---")
                    st.write(f"　- 用語: {detail.get('term_name', 'N/A')}")
                    st.write(f"　- 説明: {detail.get('term_definition', 'N/A')}")
                    example = detail.get('term_example', 'N/A')
                    if example != 'N/A' and example != '':
                        st.write(f"　- 例文: {example}")
                    st.markdown("---")

                if st.button("テストを終了する", key="end_test_after_finish"):
                    st.session_state.test_mode['is_active'] = False
                    st.session_state.test_mode['questions'] = [] 
                    st.session_state.test_mode['current_question_index'] = 0
                    st.session_state.test_mode['answers'] = []
                    st.session_state.test_mode['detailed_results'] = []
                    st.rerun()

            # 通常の問題出題
            else:
                current_question = questions[current_idx]
                st.subheader(f"問題 {current_idx + 1} / {total_questions}")
                current_correct_answers = sum(1 for i, q in enumerate(questions[:current_idx]) if st.session_state.test_mode['answers'][i] == q['correct_answer'])
                st.metric(label="現在のスコア", value=f"{current_correct_answers} / {current_idx}")
                
                st.write(f"**問題:** {current_question['question_text']}")

                with st.form(key=f"question_form_{current_idx}"):
                    default_choice_index = 0
                    if st.session_state.test_mode['answers'][current_idx] in current_question['choices']:
                        default_choice_index = current_question['choices'].index(st.session_state.test_mode['answers'][current_idx])
                    
                    selected_choice = st.radio("選択肢:", current_question['choices'], 
                                               key=f"radio_{current_idx}",
                                               index=default_choice_index) 
                    
                    submit_answer = st.form_submit_button("回答を送信")

                    if submit_answer:
                        st.session_state.test_mode['answers'][current_idx] = selected_choice 
                        
                        is_correct_current_q = (selected_choice == current_question['correct_answer'])
                        if is_correct_current_q:
                            st.success("正解！🎉")
                        else:
                            st.error(f"不正解... 😭 正解は: **{current_question['correct_answer']}**")
                        
                        st.session_state.test_mode['current_question_index'] += 1
                        st.rerun() 
                
                st.markdown("---")
                if st.button("テストを終了する (途中終了)", key="end_test_midway"):
                    st.session_state.test_mode['is_active'] = False
                    st.rerun()

    elif page == "データ管理":
        st.header("データ管理")
        
        st.subheader("全用語データのエクスポート")
        if st.button("CSVでダウンロード (用語データ)"):
            if not df_vocab.empty:
                csv = df_vocab.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="用語データをダウンロード",
                    data=csv,
                    file_name=f"{sanitized_username}_vocabulary_data_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv",
                    mime="text/csv",
                    key="download_vocab_csv"
                )
            else:
                st.info("ダウンロードする用語データがありません。")

        st.markdown("---")
        st.subheader("用語データの一括インポート (CSV)")
        st.warning("⚠️ **注意**: インポートを行うと、既存のデータが上書きされる可能性があります。事前にデータをダウンロードしてバックアップを取ることを強く推奨します。")
        uploaded_file = st.file_uploader("CSVファイルをアップロードしてください", type=["csv"])
        if uploaded_file is not None:
            try:
                uploaded_df = pd.read_csv(uploaded_file)
                required_cols = ['用語 (Term)', '説明 (Definition)', 'カテゴリ (Category)']
                if not all(col in uploaded_df.columns for col in required_cols):
                    st.error(f"CSVファイルには以下の必須カラムが含まれている必要があります: {', '.join(required_cols)}")
                else:
                    if st.button("インポートを実行 (既存データ上書きの可能性あり)"):
                        uploaded_df['ID'] = range(1, len(uploaded_df) + 1)
                        if '学習進捗 (Progress)' not in uploaded_df.columns:
                            uploaded_df['学習進捗 (Progress)'] = 'Not Started'
                        if '例文 (Example)' not in uploaded_df.columns:
                            uploaded_df['例文 (Example)'] = ''

                        final_cols = ['ID', '用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)', '学習進捗 (Progress)']
                        for col in final_cols:
                            if col not in uploaded_df.columns:
                                uploaded_df[col] = '' 
                        uploaded_df = uploaded_df[final_cols]

                        if write_data_to_gas(uploaded_df, current_worksheet_name):
                            st.success("用語データが正常にインポートされました！")
                            st.rerun()
            except Exception as e:
                st.error(f"ファイルの読み込みまたは処理中にエラーが発生しました: {e}")

        st.markdown("---")
        st.subheader("過去のテスト結果")
        if not df_test_results.empty:
            df_test_results_display = df_test_results.copy()
            
            # 'Details' カラムが存在するかチェックし、存在しない場合は空のリストをデフォルトとする
            if 'Details' not in df_test_results_display.columns:
                df_test_results_display['Details'] = '[]' # デフォルト値を設定

            df_test_results_display['Date'] = df_test_results_display['Date'].dt.strftime("%Y-%m-%d %H:%M:%S")
            
            for idx, row in df_test_results_display.iterrows():
                with st.expander(f"テスト日時: {row['Date']} | カテゴリ: {row['Category']} | 形式: {row['TestType']} | スコア: {row['Score']} / {row['TotalQuestions']}"):
                    st.write(f"---")
                    st.write(f"**テスト詳細:**")
                    try:
                        # json.loads() の前に NaN チェック
                        details_str = row['Details']
                        details = json.loads(details_str) if pd.notna(details_str) and details_str.strip() else []

                        for i, detail in enumerate(details):
                            is_correct_icon = "✅" if detail.get('is_correct') else "❌" # .get() を使用
                            st.write(f"**問題 {i+1}** {is_correct_icon}")
                            st.write(f"　- 正解: {detail.get('correct_answer', 'N/A')}")
                            st.write(f"　- あなたの回答: {detail.get('user_answer', 'N/A')}")
                            st.write("---辞書情報---") 
                            st.write(f"　- 用語: {detail.get('term_name', 'N/A')}")
                            st.write(f"　- 説明: {detail.get('term_definition', 'N/A')}")
                            example = detail.get('term_example', 'N/A')
                            if example != 'N/A' and example != '':
                                st.write(f"　- 例文: {example}")
                            st.markdown("---")
                    except json.JSONDecodeError as json_err:
                        st.error(f"テスト詳細の読み込み中にJSON解析エラーが発生しました: {json_err}。データが破損している可能性があります。元のデータ: {row['Details']}")
                    except Exception as e:
                        st.error(f"テスト詳細の表示中に予期せぬエラーが発生しました: {e}")
            
            st.markdown("---")
            if st.button("CSVでダウンロード (テスト結果)"):
                csv_test_results = df_test_results_display.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="テスト結果をダウンロード",
                    data=csv_test_results,
                    file_name=f"{sanitized_username}_test_results_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv",
                    mime="text/csv",
                    key="download_test_results_csv"
                )

        else:
            st.info("過去のテスト結果はまだありません。テストモードでテストを実施してください。")