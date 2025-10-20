import streamlit as st
import pandas as pd
import requests
import json
import os
import random
from datetime import datetime, date

# --- 設定項目 ---
GAS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbyCILybwLG84jeJamJJxfrBc6p3rDA-EU5bSkx9MdE2RMWoz6GCJmPNgLjwabfUcT31jQ/exec" # ★★★ 自分のGAS_WEBAPP_URLに置き換える ★★★
GAS_API_KEY = "my_streamlit_secret_key_123" # ★★★ 自分のGAS_API_KEYに置き換える ★★★

# ヘッダー定義
VOCAB_HEADERS = ['ID', '用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)', '学習進捗 (Progress)']
TEST_RESULTS_HEADERS = ['Date', 'Category', 'TestType', 'Score', 'TotalQuestions', 'Details']

# --- Streamlit アプリケーションの開始 ---
st.set_page_config(layout="wide")
st.title("ビジネス用語集ビルダー")

if 'username' not in st.session_state:
    st.session_state.username = None
if 'current_page' not in st.session_state:
    st.session_state.current_page = "Welcome" # 初期ページをWelcomeに設定

# --- GAS APIとの連携関数 ---
# カスタムJSONエンコーダー
def json_serial_for_gas(obj):
    """datetime, date, Pandas TimestampオブジェクトをISOフォーマット文字列に変換するカスタムJSONシリアライザー"""
    if isinstance(obj, (datetime, pd.Timestamp, date)):
        return obj.isoformat()
    # PandasのInt64の場合もPythonのintに変換
    if isinstance(obj, pd.Int64Dtype.type):
        return int(obj)
    # Numpy booleanをPython booleanに変換
    if isinstance(obj, (bool, pd.api.types.infer_dtype(obj) == 'boolean')):
        return bool(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

@st.cache_data(ttl=60)
def load_data_from_gas(sheet_name):
    try:
        params = {'api_key': GAS_API_KEY, 'sheet': sheet_name, 'action': 'read_data'}
        response = requests.get(GAS_WEBAPP_URL, params=params)
        response.raise_for_status() # HTTPエラーが発生した場合に例外を発生させる

        data = response.json()

        if 'error' in data:
            if "シートが見つかりません" in data['error'] or "Sheet not found" in data['error']:
                st.info(f"スプレッドシートに '{sheet_name}' が見つかりませんでした。新しく作成されます。")
                if sheet_name.startswith("Sheet_TestResults_"):
                    return pd.DataFrame(columns=TEST_RESULTS_HEADERS)
                else:
                    return pd.DataFrame(columns=VOCAB_HEADERS)
            else:
                st.error(f"GASからエラーが返されました: {data['error']}")
                return pd.DataFrame(columns=TEST_RESULTS_HEADERS if sheet_name.startswith("Sheet_TestResults_") else VOCAB_HEADERS)
        
        if 'data' not in data or not data['data']:
            if sheet_name.startswith("Sheet_TestResults_"):
                return pd.DataFrame(columns=TEST_RESULTS_HEADERS)
            else:
                return pd.DataFrame(columns=VOCAB_HEADERS)

        gas_values = data['data']
        
        # ヘッダーとデータを分離
        if not gas_values:
             if sheet_name.startswith("Sheet_TestResults_"):
                 return pd.DataFrame(columns=TEST_RESULTS_HEADERS)
             else:
                 return pd.DataFrame(columns=VOCAB_HEADERS)

        header = gas_values[0]
        rows = gas_values[1:]
        df = pd.DataFrame(rows, columns=header)

        if not sheet_name.startswith("Sheet_TestResults_"): # 通常の用語シートの場合
            for col in VOCAB_HEADERS:
                if col not in df.columns:
                    df[col] = pd.NA
            df = df[VOCAB_HEADERS]

            df['ID'] = pd.to_numeric(df['ID'], errors='coerce').fillna(0).astype('Int64')
            df['学習進捗 (Progress)'] = df['学習進捗 (Progress)'].fillna('Not Started')
            df['例文 (Example)'] = df['例文 (Example)'].fillna('')
            df = df.dropna(subset=['用語 (Term)', '説明 (Definition)'], how='all')
            df = df.drop_duplicates(subset=['用語 (Term)', '説明 (Definition)'], keep='first')
            df = df.sort_values(by='ID').reset_index(drop=True)
            
        else: # テスト結果シートの場合
            for col in TEST_RESULTS_HEADERS:
                if col not in df.columns:
                    df[col] = pd.NA
            df = df[TEST_RESULTS_HEADERS]

            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                df = df.dropna(subset=['Date'])
                if not df.empty:
                    df = df.sort_values(by='Date', ascending=False).reset_index(drop=True)
            
            if 'Details' in df.columns and not df.empty:
                def parse_json_safely(json_str):
                    if pd.isna(json_str) or not isinstance(json_str, str) or not json_str.strip():
                        return []
                    try:
                        return json.loads(json_str)
                    except (json.JSONDecodeError, TypeError):
                        st.warning(f"テスト結果の詳細データをJSONとしてパースできませんでした: {json_str[:100]}...")
                        return []
                df['Details'] = df['Details'].apply(parse_json_safely)
            else:
                df['Details'] = [[] for _ in range(len(df))]

        return df
    except requests.exceptions.HTTPError as e:
        st.error(f"GAS Webアプリへの接続に失敗しました: {e}")
        st.info(f"GAS WebアプリのURL: {GAS_WEBAPP_URL} が正しいか、デプロイされているか、またはGAS側のスクリプトにエラーがないか確認してください。")
        return pd.DataFrame(columns=TEST_RESULTS_HEADERS if sheet_name.startswith("Sheet_TestResults_") else VOCAB_HEADERS)
    except requests.exceptions.RequestException as e:
        st.error(f"GAS Webアプリへの接続に失敗しました: {e}")
        st.info(f"GAS WebアプリのURL: {GAS_WEBAPP_URL} が正しいか、デプロイされているか確認してください。")
        return pd.DataFrame(columns=TEST_RESULTS_HEADERS if sheet_name.startswith("Sheet_TestResults_") else VOCAB_HEADERS)
    except json.JSONDecodeError as e:
        st.error(f"GASからのレスポンスをJSONとして解析できませんでした。エラー: {e}。レスポンス内容: {response.text}。GASのコードを確認してください。")
        return pd.DataFrame(columns=TEST_RESULTS_HEADERS if sheet_name.startswith("Sheet_TestResults_") else VOCAB_HEADERS)
    except Exception as e:
        st.error(f"データの読み込み中に予期せぬエラーが発生しました: {e}")
        return pd.DataFrame(columns=TEST_RESULTS_HEADERS if sheet_name.startswith("Sheet_TestResults_") else VOCAB_HEADERS)

def write_data_to_gas(df, sheet_name, action='write_data'):
    try:
        df_to_send = df.copy()

        processed_data_rows = []
        for _, row in df_to_send.iterrows():
            processed_row = []
            for col_name, item in row.items():
                if pd.isna(item):
                    processed_row.append(None)
                elif isinstance(item, (datetime, pd.Timestamp, date)):
                    processed_row.append(item.isoformat())
                elif isinstance(item, (list, dict)):
                    try:
                        # JSONシリアライズにjson_serial_for_gasカスタムエンコーダーを使用
                        processed_row.append(json.dumps(item, ensure_ascii=False, default=json_serial_for_gas))
                    except TypeError as e:
                        st.error(f"JSONシリアライズエラー: {e} - 問題のデータ (カラム: {col_name}): {item}")
                        processed_row.append(str(item))
                elif isinstance(item, pd.Int64Dtype.type): # PandasのInt64型をPythonのintに変換
                    processed_row.append(int(item))
                elif isinstance(item, bool): # Pythonのboolはそのまま
                    processed_row.append(item)
                elif pd.api.types.is_bool_dtype(df_to_send[col_name]) and pd.notna(item): # Pandasのbool dtypeをPythonのboolに
                    processed_row.append(bool(item))
                else:
                    processed_row.append(item)
            processed_data_rows.append(processed_row)

        if action == 'append_row':
            if len(processed_data_rows) != 1:
                raise ValueError("append_row action expects exactly one row of data.")
            data_to_send = processed_data_rows[0]
        else:
            data_to_send = [df_to_send.columns.tolist()] + processed_data_rows
        
        params = {'api_key': GAS_API_KEY, 'sheet': sheet_name, 'action': action}
        headers = {'Content-Type': 'application/json'}
        response = requests.post(GAS_WEBAPP_URL, params=params, headers=headers, json={'data': data_to_send})
        response.raise_for_status()
        result = response.json()

        if 'error' in result:
            st.error(f"GAS書き込み中にエラーが返されました: {result['error']}")
            return False
        
        st.cache_data.clear()
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"GAS Webアプリへの書き込み接続に失敗しました: {e}")
        st.info(f"GAS WebアプリのURL: {GAS_WEBAPP_URL} が正しいか、デプロイされているか確認してください。")
        return False
    except json.JSONDecodeError as e:
        st.error(f"GASからのレスポンスをJSONとして解析できませんでした。エラー: {e}。レスポンス内容: {response.text}。GASのコードを確認してください。")
        return False
    except Exception as e:
        st.error(f"データの書き込み中に予期せぬエラーが発生しました: {e}")
        return False

# --- ユーザーログイン後のメインコンテンツ ---
if st.session_state.username:
    st.sidebar.write(f"ようこそ、**{st.session_state.username}** さん！")
    
    sanitized_username = "".join(filter(str.isalnum, st.session_state.username))
    current_worksheet_name = f"Sheet_{sanitized_username}"
    test_results_sheet_name = f"Sheet_TestResults_{sanitized_username}"

    # Welcomeページ以外ではデータをロード
    if st.session_state.current_page != "Welcome":
        df_vocab = load_data_from_gas(current_worksheet_name)
        df_test_results = load_data_from_gas(test_results_sheet_name) 
    else:
        df_vocab = pd.DataFrame(columns=VOCAB_HEADERS) # Welcomeページでは空のDataFrame
        df_test_results = pd.DataFrame(columns=TEST_RESULTS_HEADERS)

    if 'test_mode' not in st.session_state:
        st.session_state.test_mode = {
            'is_active': False,
            'test_type': None,
            'question_source': None,
            'selected_category': '全てのカテゴリ',
            'questions': [],
            'current_question_index': 0,
            'score': 0,
            'answers': [],
            'detailed_results': []
        }
    
    if 'learning_mode' not in st.session_state:
        st.session_state.learning_mode = {
            'filtered_df_indices': [],
            'current_index_in_filtered': 0,
            'selected_category': '全てのカテゴリ',
            'progress_filter': '全ての進捗'
        }

    if 'dictionary_mode' not in st.session_state:
        st.session_state.dictionary_mode = {
            'search_term': '',
            'selected_category': '全てのカテゴリ',
            'expanded_term_id': None
        }

    # --- テスト問題生成ヘルパー関数 ---
    def generate_questions_for_test(test_type, question_source, category_filter='全てのカテゴリ', num_questions=10):
        eligible_vocab_df = df_vocab.copy()

        if question_source == 'category' and category_filter != '全てのカテゴリ':
            eligible_vocab_df = eligible_vocab_df[eligible_vocab_df['カテゴリ (Category)'] == category_filter]
        
        if test_type == 'example_to_term':
            eligible_vocab_df = eligible_vocab_df[pd.notna(eligible_vocab_df['例文 (Example)']) & (eligible_vocab_df['例文 (Example)'] != '')]

        if eligible_vocab_df.empty or len(eligible_vocab_df) < 4: # 最低4つの選択肢を生成するため
            return None 
        
        actual_num_questions = min(num_questions, len(eligible_vocab_df))
        if actual_num_questions == 0:
            return None

        selected_terms = eligible_vocab_df.sample(n=actual_num_questions, replace=False, random_state=random.randint(0, 10000))
        
        questions_list = []
        for _, question_term_row in selected_terms.iterrows():
            correct_answer = ""
            question_text = ""
            all_options_pool = []

            if test_type == 'term_to_def':
                question_text = question_term_row['用語 (Term)']
                correct_answer = question_term_row['説明 (Definition)']
                all_options_pool = eligible_vocab_df['説明 (Definition)'].dropna().unique().tolist()
            elif test_type == 'example_to_term':
                question_text = question_term_row['例文 (Example)']
                correct_answer = question_term_row['用語 (Term)']
                all_options_pool = eligible_vocab_df['用語 (Term)'].dropna().unique().tolist()
            
            possible_incorrects = [opt for opt in all_options_pool if opt != correct_answer]
            
            incorrect_choices = []
            if len(possible_incorrects) >= 3:
                incorrect_choices = random.sample(possible_incorrects, 3)
            elif possible_incorrects:
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
        
        generated_questions = generate_questions_for_test(test_type, question_source, category_filter, num_questions=10)
        
        if generated_questions is None or not generated_questions:
            st.error("テスト問題を作成できませんでした。出題条件を満たす用語が不足している可能性があります。")
            st.session_state.test_mode['is_active'] = False
            return

        st.session_state.test_mode['questions'] = generated_questions
        st.session_state.test_mode['current_question_index'] = 0 
        st.session_state.test_mode['score'] = 0
        st.session_state.test_mode['answers'] = [None] * len(st.session_state.test_mode['questions'])
        st.session_state.test_mode['detailed_results'] = []
        
        st.rerun()

    # --- テストモードの再開 ---
    def resume_test():
        st.session_state.test_mode['is_active'] = True
        st.rerun()

    # --- テスト結果と学習進捗をGASに書き込む関数 ---
    def save_test_results_and_progress():
        global df_vocab, df_test_results

        questions = st.session_state.test_mode['questions']
        user_answers = st.session_state.test_mode['answers']
        
        final_score = 0
        current_detailed_results = []
        updated_vocab_ids = set()

        for i, q in enumerate(questions):
            user_ans = user_answers[i]
            is_correct = (user_ans == q['correct_answer'])
            if is_correct:
                final_score += 1
            
            current_detailed_results.append({
                'question_text': q['question_text'],
                'correct_answer': q['correct_answer'],
                'user_answer': user_ans if user_ans is not None else "未回答",
                'is_correct': is_correct,
                'term_id': q.get('term_id'),
                'term_name': q.get('term_name', 'N/A'), 
                'term_definition': q.get('term_definition', 'N/A'), 
                'term_example': q.get('term_example', 'N/A') 
            })

            original_df_index = df_vocab[df_vocab['ID'] == q['term_id']].index
            if not original_df_index.empty:
                row_idx = original_df_index[0]
                current_progress = df_vocab.loc[row_idx, '学習進捗 (Progress)']
                
                if is_correct:
                    if current_progress == 'Not Started':
                        df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Learning'
                    elif current_progress == 'Learning':
                        df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Mastered'
                else:
                    if current_progress == 'Mastered':
                        df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Learning'
                    elif current_progress == 'Learning':
                        df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Not Started'
                updated_vocab_ids.add(q['term_id'])

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

        new_result_df_for_gas = pd.DataFrame([{
            'Date': test_date_obj,
            'Category': category_used,
            'TestType': test_type_display,
            'Score': final_score,
            'TotalQuestions': len(questions),
            'Details': current_detailed_results
        }])
        
        write_success_results = write_data_to_gas(new_result_df_for_gas, test_results_sheet_name, action='append_row')

        if write_success_results:
            if df_test_results.empty:
                df_test_results = pd.DataFrame(columns=TEST_RESULTS_HEADERS)
            df_test_results = pd.concat([df_test_results, new_result_df_for_gas], ignore_index=True)
            st.success("テスト結果が保存されました！「データ管理」から確認できます。")
        else:
            st.error("テスト結果の保存に失敗しました。")

        if updated_vocab_ids:
            write_success_vocab = write_data_to_gas(df_vocab, current_worksheet_name)
            if write_success_vocab:
                st.success("学習進捗が更新されました！")
            else:
                st.error("学習進捗の更新に失敗しました。")


    # --- ナビゲーション ---
    st.sidebar.header("ナビゲーション")
    
    sidebar_options = [
        "Welcome",
        "学習モード",
        "テストモード",
        "辞書モード",
        "用語一覧", 
        "用語の追加・編集",
        "データ管理"
    ]
    
    # st.session_state.current_page を使用して、選択されたページを管理
    page_index = sidebar_options.index(st.session_state.current_page)
    new_page_selection = st.sidebar.radio("Go to", sidebar_options, index=page_index, key="sidebar_navigator")

    if new_page_selection != st.session_state.current_page:
        st.session_state.current_page = new_page_selection
        st.rerun()

    # --- 各ページの表示ロジック ---
    if st.session_state.current_page == "Welcome":
        st.header("Welcome to ビジネス用語集ビルダー！")
        st.write("このアプリは、あなたのビジネス用語学習をサポートします。")
        st.markdown("詳しい使い方は、以下のページをご参照ください。")
        st.markdown("[使い方ガイド（Notion）](https://www.notion.so/tacoms/285383207704802ca7cdddc3a7b8271f)")

        if st.session_state.username is None:
            st.info("最初にあなたの名前を入力してください。")
            with st.form("username_form_welcome"):
                input_username = st.text_input("あなたの名前を入力してください")
                submit_username = st.form_submit_button("進む")
                if submit_username and input_username:
                    st.session_state.username = input_username
                    st.session_state.current_page = "学習モード" # 名前入力後、学習モードへ遷移
                    st.rerun()
        else:
            st.success(f"こんにちは、{st.session_state.username} さん！サイドバーから機能を選択して開始しましょう。")

    elif st.session_state.current_page == "用語一覧":
        st.header("登録済みビジネス用語")
        if not df_vocab.empty:
            all_categories = ['全てのカテゴリ'] + sorted(df_vocab['カテゴリ (Category)'].dropna().unique().tolist())
            selected_category = st.selectbox("カテゴリで絞り込む:", all_categories)
            filtered_df = df_vocab.copy()
            if selected_category != '全てのカテゴリ':
                filtered_df = filtered_df[filtered_df['カテゴリ (Category)'] == selected_category]
            search_term = st.text_input("用語や説明を検索:")
            if search_term:
                search_lower = search_term.lower()
                filtered_df = filtered_df[
                    filtered_df.apply(lambda row: 
                                      search_lower in str(row['用語 (Term)']).lower() or
                                      search_lower in str(row['説明 (Definition)']).lower() or
                                      (pd.notna(row['例文 (Example)']) and search_lower in str(row['例文 (Example)']).lower()), 
                                      axis=1)
                ]
            st.dataframe(filtered_df, use_container_width=True, hide_index=True)
        else:
            st.info("まだ用語が登録されていません。「用語の追加・編集」から追加してください。")

    elif st.session_state.current_page == "用語の追加・編集":
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
                    df_vocab = pd.concat([df_vocab, new_row], ignore_index=True)
                    if write_data_to_gas(df_vocab, current_worksheet_name):
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

    elif st.session_state.current_page == "学習モード":
        st.header("学習モード")

        if df_vocab.empty:
            st.info("学習する用語がありません。「用語の追加・編集」から追加してください。")
        else:
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
            
            filtered_df = df_vocab.copy()
            if selected_category_filter != '全てのカテゴリ':
                filtered_df = filtered_df[filtered_df['カテゴリ (Category)'] == selected_category_filter]
            if selected_progress_filter != '全ての進捗':
                filtered_df = filtered_df[filtered_df['学習進捗 (Progress)'] == selected_progress_filter]

            if (selected_category_filter != st.session_state.learning_mode['selected_category'] or
                selected_progress_filter != st.session_state.learning_mode['progress_filter'] or
                not st.session_state.learning_mode['filtered_df_indices'] or
                set(st.session_state.learning_mode['filtered_df_indices']) != set(filtered_df.index.tolist())
                ):
                st.session_state.learning_mode['selected_category'] = selected_category_filter
                st.session_state.learning_mode['progress_filter'] = selected_progress_filter
                st.session_state.learning_mode['filtered_df_indices'] = filtered_df.index.tolist()
                st.session_state.learning_mode['current_index_in_filtered'] = 0
                st.rerun()

            if filtered_df.empty:
                st.info("この条件に一致する用語は見つかりませんでした。")
                st.session_state.learning_mode['filtered_df_indices'] = []
                st.session_state.learning_mode['current_index_in_filtered'] = 0
            
            if not filtered_df.empty:
                total_terms_in_filtered = len(filtered_df)
                current_display_index_in_filtered = st.session_state.learning_mode['current_index_in_filtered']

                if current_display_index_in_filtered >= total_terms_in_filtered:
                    st.session_state.learning_mode['current_index_in_filtered'] = 0
                    current_display_index_in_filtered = 0

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

    elif st.session_state.current_page == "辞書モード":
        st.header("辞書モード")

        if df_vocab.empty:
            st.info("辞書に登録された用語がありません。「用語の追加・編集」から追加してください。")
        else:
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
                    expander_key = f"expander_{row['ID']}"
                    
                    is_expanded = (st.session_state.dictionary_mode['expanded_term_id'] == row['ID'])

                    with st.expander(f"**{row['用語 (Term)']}. （カテゴリ: {row['カテゴリ (Category)']}）**", 
                                      expanded=is_expanded):
                        st.write(f"### 説明")
                        st.markdown(f"**{row['説明 (Definition)']}**")
                        if pd.notna(row['例文 (Example)']) and row['例文 (Example)'] != '':
                            st.write(f"### 例文")
                            st.markdown(f"*{row['例文 (Example)']}*")
                        
                        if st.button("閉じる", key=f"close_dict_{row['ID']}"):
                            st.session_state.dictionary_mode['expanded_term_id'] = None
                            st.rerun()
                    
                    if not is_expanded:
                        if st.button("詳細を見る", key=f"open_dict_{row['ID']}"):
                            st.session_state.dictionary_mode['expanded_term_id'] = row['ID']
                            st.rerun()
                    st.markdown("---") 

    elif st.session_state.current_page == "テストモード":
        st.header("テストモード")
        if df_vocab.empty:
            st.info("テストする用語がありません。「用語の追加・編集」から追加してください。")
        else:
            all_categories_for_test = ['全てのカテゴリ'] + sorted(df_vocab['カテゴリ (Category)'].dropna().unique().tolist())
            
            if not st.session_state.test_mode['is_active']:
                if st.session_state.test_mode['questions'] and st.session_state.test_mode['current_question_index'] < len(st.session_state.test_mode['questions']):
                    st.warning("中断中のテストがあります。")
                    if st.button("テストを再開", key="resume_test_button"):
                        resume_test()
                        st.rerun()

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
            
            else: # テストがアクティブな場合
                questions = st.session_state.test_mode['questions']
                current_idx = st.session_state.test_mode['current_question_index']
                total_questions = len(questions)

                if not questions:
                    st.error("この条件でテスト問題を作成できませんでした。用語の数や例文の有無を確認してください。")
                    if st.button("テストを終了する", key="end_test_no_q"):
                        st.session_state.test_mode['is_active'] = False
                        st.session_state.test_mode['questions'] = [] 
                        st.session_state.test_mode['current_question_index'] = 0
                        st.session_state.test_mode['answers'] = []
                        st.session_state.test_mode['detailed_results'] = []
                        st.rerun()
                elif current_idx >= total_questions:
                    st.subheader("テスト結果")
                    
                    save_test_results_and_progress()

                    final_score = st.session_state.test_mode['score']
                    st.write(f"お疲れ様でした！あなたの最終スコアは **{final_score} / {total_questions}** です。")
                    
                    st.markdown("---")
                    st.subheader("詳細結果")
                    for i, detail in enumerate(st.session_state.test_mode['detailed_results']):
                        is_correct_icon = "✅" if detail.get('is_correct') else "❌" 
                        st.write(f"**問題 {i+1}** {is_correct_icon}")
                        st.write(f"　- 問題文: {detail.get('question_text', 'N/A')}")
                        st.write(f"　- 正解: {detail.get('correct_answer', 'N/A')}")
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

                else:
                    current_question = questions[current_idx]
                    st.subheader(f"問題 {current_idx + 1} / {total_questions}")
                    
                    current_correct_answers_count = 0
                    for i in range(current_idx):
                        if st.session_state.test_mode['answers'][i] == questions[i]['correct_answer']:
                            current_correct_answers_count += 1
                    
                    st.metric(label="現在のスコア", value=f"{current_correct_answers_count} / {current_idx}")
                    
                    st.write(f"**問題:** {current_question['question_text']}")

                    with st.form(key=f"question_form_{current_idx}"):
                        default_choice_index = 0
                        if st.session_state.test_mode['answers'][current_idx] is not None and \
                           st.session_state.test_mode['answers'][current_idx] in current_question['choices']:
                            try:
                                default_choice_index = current_question['choices'].index(st.session_state.test_mode['answers'][current_idx])
                            except ValueError:
                                default_choice_index = 0
                        
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
    
    elif st.session_state.current_page == "データ管理":
        st.header("データ管理")

        if df_test_results.empty:
            st.info("まだテスト結果が保存されていません。")
        else:
            st.subheader("テスト結果履歴")
            
            if 'expanded_test_result_index' not in st.session_state:
                st.session_state.expanded_test_result_index = None

            for i, row in df_test_results.iterrows():
                test_date_str = row['Date'].strftime('%Y-%m-%d %H:%M') if pd.notna(row['Date']) else "日付不明"
                score_str = f"{row['Score']} / {row['TotalQuestions']}"
                header_text = f"**{test_date_str}** - カテゴリ: {row['Category']}, タイプ: {row['TestType']}, スコア: {score_str}"
                
                is_expanded = (st.session_state.expanded_test_result_index == i)

                with st.expander(header_text, expanded=is_expanded):
                    st.write(f"---詳細---")
                    details = row['Details']
                    if details:
                        for j, detail in enumerate(details):
                            is_correct_icon = "✅" if detail.get('is_correct') else "❌"
                            st.markdown(f"**問題 {j+1}** {is_correct_icon}")
                            st.write(f"　- 問題文: {detail.get('question_text', 'N/A')}")
                            st.write(f"　- 正解: {detail.get('correct_answer', 'N/A')}")
                            st.write(f"　- あなたの回答: {detail.get('user_answer', 'N/A')}")
                            st.write("　---用語情報---")
                            st.write(f"　　- 用語: {detail.get('term_name', 'N/A')}")
                            st.write(f"　　- 説明: {detail.get('term_definition', 'N/A')}")
                            example = detail.get('term_example', 'N/A')
                            if example != 'N/A' and example != '':
                                st.write(f"　　- 例文: {example}")
                            st.markdown("---")
                    else:
                        st.info("このテストの詳細は記録されていません。")
                    
                    col_close, col_delete_result = st.columns([1, 1])
                    with col_close:
                        if st.button("閉じる", key=f"close_result_{i}"):
                            st.session_state.expanded_test_result_index = None
                            st.rerun()
                    with col_delete_result:
                        # 削除ボタンを押したら確認フォームを表示
                        if st.button("この結果を削除", key=f"delete_result_{i}"):
                            st.session_state[f'confirm_delete_{i}'] = True
                            st.rerun() # 確認フォームを表示するために再描画
                
                # 削除確認フォームはexpanderの外で制御
                if st.session_state.get(f'confirm_delete_{i}', False):
                    st.warning("本当にこのテスト結果を削除しますか？")
                    with st.form(key=f"confirm_delete_form_{i}"):
                        confirm_delete = st.form_submit_button("はい、削除します")
                        cancel_delete = st.form_submit_button("キャンセル")

                        if confirm_delete:
                            df_test_results = df_test_results.drop(index=i).reset_index(drop=True)
                            if write_data_to_gas(df_test_results, test_results_sheet_name):
                                st.success("テスト結果が削除されました。")
                                st.session_state.expanded_test_result_index = None
                                st.session_state[f'confirm_delete_{i}'] = False # 確認フォームを閉じる
                                st.cache_data.clear() # df_test_resultsを再ロードするためにキャッシュクリア
                                st.rerun()
                            else:
                                st.error("テスト結果の削除に失敗しました。")
                        elif cancel_delete:
                            st.info("削除をキャンセルしました。")
                            st.session_state[f'confirm_delete_{i}'] = False # 確認フォームを閉じる
                            st.rerun()
                
                # 詳細を見る/閉じるボタンをexpanderの外で制御する
                if not is_expanded and not st.session_state.get(f'confirm_delete_{i}', False): # 削除確認フォームが表示されていない場合のみ
                    if st.button("詳細を見る", key=f"open_result_{i}"):
                        st.session_state.expanded_test_result_index = i
                        st.rerun()
                st.markdown("---")
