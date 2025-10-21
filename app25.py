import streamlit as st
import pandas as pd
import requests
import json
import os
import random
from datetime import datetime, date

# --- 設定項目 ---
# ★★★ 自分のGAS_WEBAPP_URLに置き換える ★★★
# このURLはGASプロジェクトをデプロイした後に発行されます
GAS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbzFvhOrTCvfOopTPT87wUUrSTKk1AUqzSN9cUAAu5Sbl1Y4xKaxQ9MflmFKcZGVM5Fr-w/exec" 
# ★★★ 自分のGAS_API_KEYに置き換える ★★★
GAS_API_KEY = "my_streamlit_secret_key_123" 

# ヘッダー定義
VOCAB_HEADERS = ['ID', '用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)', '学習進捗 (Progress)']
TEST_RESULTS_HEADERS = ['Date', 'Category', 'TestType', 'Score', 'TotalQuestions', 'Details']

# --- Streamlit アプリケーションの開始 ---
st.set_page_config(layout="wide")
st.title("ビジネス用語集ビルダー")

# --- ページ遷移関数 (ここに追加) ---
def go_to_page(page_name):
    st.session_state.current_page = page_name
    st.rerun()

# st.session_state の初期化
if 'username' not in st.session_state:
    st.session_state.username = None
if 'current_page' not in st.session_state:
    st.session_state.current_page = "Welcome"
if 'vocab_data_loaded' not in st.session_state: # データロード済みフラグ
    st.session_state.vocab_data_loaded = False
if 'test_mode' not in st.session_state:
    st.session_state.test_mode = {
        'active': False,
        'current_question_index': 0,
        'questions': [],
        'answers': [],
        'score': 0,
        'detailed_results': [],
        'selected_category': '全カテゴリ',
        'question_count': 10,
        'test_type': 'term_to_def', # 'term_to_def' or 'example_to_term'
        'question_source': 'random_all' # 'random_all', 'learning_focus'
    }
if 'test_review_mode' not in st.session_state:
    st.session_state.test_review_mode = {
        'active': False,
        'review_index': 0,
        'results_to_review': []
    }
# df_vocab と df_test_results もセッションステートで管理する
if 'df_vocab' not in st.session_state:
    st.session_state.df_vocab = pd.DataFrame(columns=VOCAB_HEADERS)
if 'df_test_results' not in st.session_state:
    st.session_state.df_test_results = pd.DataFrame(columns=TEST_RESULTS_HEADERS)


# ユーザー名に応じたスプレッドシート名の設定 (usernameがNoneの場合は一時的なデフォルト)
current_worksheet_name = f"Sheet_Vocab_{st.session_state.username}" if st.session_state.username else "Sheet_Vocab_Default"
test_results_sheet_name = f"Sheet_TestResults_{st.session_state.username}" if st.session_state.username else "Sheet_TestResults_Default"

# --- GAS APIとの連携関数 ---
# カスタムJSONエンコーダー
def json_serial_for_gas(obj):
    """datetime, date, Pandas TimestampオブジェクトをISOフォーマット文字列に変換するカスタムJSONシライザー"""
    if isinstance(obj, (datetime, pd.Timestamp, date)):
        return obj.isoformat()
    # Pandasの整数型、浮動小数点数型、真偽値型をPythonの基本型に変換
    if isinstance(obj, pd.Int64Dtype.type):
        return int(obj)
    if isinstance(obj, pd.BooleanDtype().type):
        return bool(obj)
    if isinstance(obj, float) and pd.isna(obj): # NaNをNoneに変換 (JSONではnullになる)
        return None
    
    # NumPyの型も考慮
    if hasattr(obj, 'dtype'):
        if str(obj.dtype).startswith('int'): return int(obj)
        if str(obj.dtype).startswith('float'): return float(obj)
        if str(obj.dtype).startswith('bool'): return bool(obj)

    # DataFrame内の特定のセルがlistやdictの場合、json.dumpsで再帰的に処理する
    if isinstance(obj, (dict, list)):
        return json.dumps(obj, ensure_ascii=False, default=json_serial_for_gas)

    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

@st.cache_data(ttl=60)
def load_data_from_gas(sheet_name):
    st.sidebar.write(f"DEBUG: Attempting to load data from sheet: {sheet_name}")
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
                st.sidebar.write(f"DEBUG: GAS Error during read: {data['error']}")
                return pd.DataFrame(columns=TEST_RESULTS_HEADERS if sheet_name.startswith("Sheet_TestResults_") else VOCAB_HEADERS)
        
        if 'data' not in data or not data['data']:
            st.sidebar.write(f"DEBUG: No data found in sheet '{sheet_name}'. Returning empty DataFrame.")
            if sheet_name.startswith("Sheet_TestResults_"):
                return pd.DataFrame(columns=TEST_RESULTS_HEADERS)
            else:
                return pd.DataFrame(columns=VOCAB_HEADERS)

        gas_values = data['data']
        
        # ヘッダーとデータを分離
        if not gas_values:
             st.sidebar.write(f"DEBUG: gas_values is empty for sheet '{sheet_name}'. Returning empty DataFrame.")
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
                        st.warning(f"テスト結果の詳細データをJSONとしてパースできませんでした: {str(json_str)[:200]}...")
                        return []
                df['Details'] = df['Details'].apply(parse_json_safely)
            else:
                df['Details'] = [[] for _ in range(len(df))]

        st.sidebar.write(f"DEBUG: Successfully loaded {len(df)} rows from sheet '{sheet_name}'.")
        return df
    except requests.exceptions.HTTPError as e:
        st.error(f"GAS Webアプリへの接続に失敗しました: {e}")
        st.info(f"GAS WebアプリのURL: {GAS_WEBAPP_URL} が正しいか、デプロイされているか、またはGAS側のスクリプトにエラーがないか確認してください。")
        st.sidebar.write(f"DEBUG: HTTP Error: {e}")
        return pd.DataFrame(columns=TEST_RESULTS_HEADERS if sheet_name.startswith("Sheet_TestResults_") else VOCAB_HEADERS)
    except requests.exceptions.RequestException as e:
        st.error(f"GAS Webアプリへの接続に失敗しました: {e}")
        st.info(f"GAS WebアプリのURL: {GAS_WEBAPP_URL} が正しいか、デプロイされているか確認してください。")
        st.sidebar.write(f"DEBUG: Request Error: {e}")
        return pd.DataFrame(columns=TEST_RESULTS_HEADERS if sheet_name.startswith("Sheet_TestResults_") else VOCAB_HEADERS)
    except json.JSONDecodeError as e:
        st.error(f"GASからのレスポンスをJSONとして解析できませんでした。エラー: {e}。レスポンス内容: {response.text}。GASのコードを確認してください。")
        st.sidebar.write(f"DEBUG: JSON Decode Error: {e}, Response: {response.text}")
        return pd.DataFrame(columns=TEST_RESULTS_HEADERS if sheet_name.startswith("Sheet_TestResults_") else VOCAB_HEADERS)
    except Exception as e:
        st.error(f"データの読み込み中に予期せぬエラーが発生しました: {e}")
        st.exception(e)
        st.sidebar.write(f"DEBUG: Unexpected Error during load: {e}")
        return pd.DataFrame(columns=TEST_RESULTS_HEADERS if sheet_name.startswith("Sheet_TestResults_") else VOCAB_HEADERS)

def write_data_to_gas(df, sheet_name, action='write_data'):
    try:
        # 'Details'カラムを事前にJSON文字列に変換
        if sheet_name.startswith("Sheet_TestResults_") and 'Details' in df.columns:
            df_to_send = df.copy() # 送信用にコピー
            df_to_send['Details'] = df_to_send['Details'].apply(
                lambda x: json.dumps(x, ensure_ascii=False, default=json_serial_for_gas) if not pd.isna(x) else ''
            )
        else:
            df_to_send = df.copy()
        
        # DataFrameをJSON文字列に変換
        df_json_str = df_to_send.to_json(orient='split', date_format='iso', default=json_serial_for_gas, force_ascii=False)
        
        # GASに送信するデータペイロードを構築
        payload = {
            'api_key': GAS_API_KEY,
            'sheet': sheet_name,
            'action': action,
            'data': df_json_str # DataFrame全体をJSON文字列として送信
        }
        
        st.sidebar.write(f"DEBUG: Data payload being sent to GAS (first 500 chars of data): {str(payload['data'])[:500]}...")
        st.sidebar.write(f"DEBUG: Action: {action}, Sheet: {sheet_name}")

        headers = {'Content-Type': 'application/json'}
        response = requests.post(GAS_WEBAPP_URL, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()

        if 'error' in result:
            st.error(f"GAS書き込み中にエラーが返されました: {result['error']}")
            st.sidebar.write(f"DEBUG: GAS Error Response: {result['error']}")
            return False
        
        st.cache_data.clear() # キャッシュをクリアして、次回の読み込みで最新データを取得させる
        st.sidebar.write(f"DEBUG: Data successfully written to GAS for sheet '{sheet_name}'.")
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"GAS Webアプリへの書き込み接続に失敗しました: {e}")
        st.info(f"GAS WebアプリのURL: {GAS_WEBAPP_URL} が正しいか、デプロイされているか確認してください。")
        st.exception(e)
        st.sidebar.write(f"DEBUG: Request Error during write: {e}")
        return False
    except json.JSONDecodeError as e:
        st.error(f"GASからのレスポンスをJSONとして解析できませんでした。エラー: {e}。レスポンス内容: {response.text}。GASのコードを確認してください。")
        st.exception(e)
        st.sidebar.write(f"DEBUG: JSON Decode Error during write: {e}, Response: {response.text}")
        return False
    except Exception as e:
        st.error(f"データの書き込み中に予期せぬエラーが発生しました: {e}")
        st.exception(e)
        st.sidebar.write(f"DEBUG: Unexpected Error during write: {e}")
        return False

# --- メインロジック ---

# ユーザー名が設定されていない場合（ログイン前）は、ログインフォームを表示
if st.session_state.username is None:
    st.session_state.current_page = "Welcome" # 念のためcurrent_pageをWelcomeに設定
    st.header("Welcome to ビジネス用語集ビルダー！")
    st.write("このアプリは、あなたのビジネス用語学習をサポートします。")
    st.markdown("詳しい使い方は、以下のページをご参照ください。")
    st.markdown("[使い方ガイド（Notion）](https://www.notion.so/tacoms/285383207704802ca7cdddc3a7b8271f)")
    st.info("最初にあなたの名前を入力してください。")
    with st.form("username_form_welcome_fallback"): # ユニークなフォームキー
        input_username = st.text_input("あなたの名前を入力してください")
        submit_username = st.form_submit_button("進む")
        if submit_username and input_username:
            st.session_state.username = input_username
            # ユーザー名が設定されたので、関連するシート名も更新
            current_worksheet_name = f"Sheet_{st.session_state.username}"
            test_results_sheet_name = f"Sheet_TestResults_{st.session_state.username}"
            # 新しいユーザー名でデータをロードし直す
            with st.spinner(f"{st.session_state.username}さんのデータをロード中..."):
                st.session_state.df_vocab = load_data_from_gas(current_worksheet_name)
                st.session_state.df_test_results = load_data_from_gas(test_results_sheet_name)
                st.session_state.vocab_data_loaded = True
            st.session_state.current_page = "学習モード" # ログイン後、学習モードへ
            st.rerun()
else: # ユーザーがログインしている場合
    # ユーザー名が設定されているが、データがまだロードされていない場合はロードする
    if not st.session_state.vocab_data_loaded:
        with st.spinner(f"{st.session_state.username}さんのデータをロード中..."):
            st.session_state.df_vocab = load_data_from_gas(f"Sheet_Vocab_{st.session_state.username}")
            st.session_state.df_test_results = load_data_from_gas(f"Sheet_TestResults_{st.session_state.username}")
            st.session_state.vocab_data_loaded = True
    
    # ここからはセッションステートからDataFrameを取得して使用
    df_vocab = st.session_state.df_vocab
    df_test_results = st.session_state.df_test_results

    # --- 共通サイドバー ---
    st.sidebar.title(f"ようこそ、{st.session_state.username}さん！")
    
    # ページ選択ボタン
    if st.sidebar.button("📊 データ管理", key="nav_data_management"):
        go_to_page("データ管理")
    if st.sidebar.button("📚 学習モード", key="nav_study_mode"):
        go_to_page("学習モード")
    if st.sidebar.button("📝 テストモード", key="nav_test_mode"):
        go_to_page("テストモード")
    if st.sidebar.button("📈 テスト結果", key="nav_test_results"):
        go_to_page("テスト結果")
    st.sidebar.markdown("---")
    
    # 新規用語追加フォーム (サイドバーに配置)
    st.sidebar.header("新規用語の追加")
    with st.sidebar.form("add_term_form"):
        new_term = st.text_input("用語", key="sidebar_new_term")
        new_definition = st.text_area("説明", key="sidebar_new_definition")
        new_example = st.text_area("例文 (任意)", key="sidebar_new_example")
        
        # カテゴリの選択肢は、df_vocabが空でなければそこから取得
        categories = df_vocab['カテゴリ (Category)'].dropna().unique().tolist() if not df_vocab.empty else []
        new_category = st.selectbox("カテゴリ", [''] + categories + ['新しいカテゴリを作成'], key="sidebar_new_category")
        
        if new_category == '新しいカテゴリを作成':
            new_category_text = st.text_input("新しいカテゴリ名を入力", key="sidebar_new_category_text")
            if new_category_text:
                new_category = new_category_text
        
        submitted = st.form_submit_button("用語を追加")
        if submitted:
            if new_term and new_definition and new_category and new_category != '新しいカテゴリを作成': # ここで新しいカテゴリ作成中の状態をチェック
                next_id = (df_vocab['ID'].max() + 1) if not df_vocab.empty else 1
                new_row = pd.DataFrame([{
                    'ID': next_id,
                    '用語 (Term)': new_term,
                    '説明 (Definition)': new_definition,
                    '例文 (Example)': new_example,
                    'カテゴリ (Category)': new_category,
                    '学習進捗 (Progress)': 'Not Started'
                }])
                df_vocab = pd.concat([df_vocab, new_row], ignore_index=True)
                if write_data_to_gas(df_vocab, current_worksheet_name):
                    st.success(f"用語 '{new_term}' を追加しました！")
                    st.session_state.df_vocab = df_vocab # セッションステートも更新
                    # 入力フィールドをクリア (Streamlitのバグ回避のためrerun)
                    st.session_state.sidebar_new_term = ""
                    st.session_state.sidebar_new_definition = ""
                    st.session_state.sidebar_new_example = ""
                    st.rerun()
                else:
                    st.error("用語の追加に失敗しました。")
            else:
                st.error("用語、説明、有効なカテゴリは必須です。")
    
    st.sidebar.markdown("---")
    if st.sidebar.button("ログアウト", key="logout_button"):
        st.session_state.username = None
        st.session_state.current_page = "Welcome"
        st.session_state.vocab_data_loaded = False # ログアウト時にデータロードフラグをリセット
        st.cache_data.clear() # キャッシュもクリア
        # セッションステートのDataFrameもクリア
        st.session_state.df_vocab = pd.DataFrame(columns=VOCAB_HEADERS)
        st.session_state.df_test_results = pd.DataFrame(columns=TEST_RESULTS_HEADERS)
        st.rerun()

    # --- メインコンテンツ ---
    if st.session_state.current_page == "データ管理":
        st.header("📊 データ管理")
        st.write("登録されているビジネス用語の一覧を表示・編集できます。")
        
        if df_vocab.empty:
            st.info("まだ用語が登録されていません。サイドバーから新しい用語を追加してください。")
            st.sidebar.write(f"DEBUG: df_vocab is empty. Columns: {df_vocab.columns.tolist()}")
        else:
            st.sidebar.write(f"DEBUG: df_vocab has {len(df_vocab)} rows.")
            edited_df = st.data_editor(
                df_vocab,
                column_config={
                    "ID": st.column_config.NumberColumn("ID", help="用語のID", width="small", disabled=True),
                    "用語 (Term)": st.column_config.TextColumn("用語 (Term)", help="ビジネス用語"),
                    "説明 (Definition)": st.column_config.TextColumn("説明 (Definition)", help="用語の説明"),
                    "例文 (Example)": st.column_config.TextColumn("例文 (Example)", help="使用例"),
                    "カテゴリ (Category)": st.column_config.SelectboxColumn("カテゴリ (Category)", help="用語のカテゴリ",
                        options=df_vocab['カテゴリ (Category)'].dropna().unique().tolist() + ['新しいカテゴリを作成'], required=True),
                    "学習進捗 (Progress)": st.column_config.SelectboxColumn("学習進捗 (Progress)", help="学習の進捗状況",
                        options=['Not Started', 'Learning', 'Mastered'], required=True)
                },
                num_rows="dynamic",
                hide_index=True,
                use_container_width=True
            )
            
            if st.button("変更を保存", key="save_data_management"):
                # 新しいカテゴリ作成時の処理
                has_category_error = False
                for idx, row in edited_df.iterrows():
                    if row['カテゴリ (Category)'] == '新しいカテゴリを作成':
                        st.error(f"行 {idx+1}: '新しいカテゴリを作成'が選択されています。有効なカテゴリを選択または入力してください。")
                        has_category_error = True
                
                if has_category_error: # カテゴリエラーがあればここで処理を停止
                    st.stop() 

                # 必須カラムのチェック
                # edited_dfにNaNを含む行があるか、および指定カラムが空文字になっていないか
                required_cols = ['用語 (Term)', '説明 (Definition)', 'カテゴリ (Category)']
                if edited_df[required_cols].isnull().values.any() or (edited_df[required_cols] == '').any().any():
                    st.error("用語、説明、カテゴリは必須です。空欄がないか確認してください。")
                    st.stop() # 必須カラムエラーがあればここで処理を停止
                else:
                    # 'ID'がNaNになっている新規行を特定し、IDを付与
                    new_rows = edited_df[edited_df['ID'].isna()]
                    for idx, row in new_rows.iterrows():
                        next_id = (df_vocab['ID'].max() + 1) if not df_vocab.empty else 1
                        edited_df.loc[idx, 'ID'] = next_id
                    
                    # edited_dfをdf_vocabに代入し、GASに書き込む
                    df_vocab = edited_df.astype({'ID': 'Int64'}) # IDをInt64型に強制
                    if write_data_to_gas(df_vocab, current_worksheet_name):
                        st.success("変更を保存しました！")
                        st.session_state.df_vocab = df_vocab # セッションステートも更新
                        st.rerun() # 変更を反映するために再実行
                    else:
                        st.error("変更の保存に失敗しました。")

    elif st.session_state.current_page == "学習モード":
        st.header("📚 学習モード")
        st.write("登録されている用語を学習できます。")

        if df_vocab.empty:
            st.info("まだ用語が登録されていません。サイドバーから新しい用語を追加してください。")
        else:
            categories = df_vocab['カテゴリ (Category)'].dropna().unique().tolist()
            selected_category_study = st.selectbox("カテゴリを選択", ['全カテゴリ'] + categories, key="study_category_selector")

            filtered_df = df_vocab
            if selected_category_study != '全カテゴリ':
                filtered_df = df_vocab[df_vocab['カテゴリ (Category)'] == selected_category_study]
            
            if filtered_df.empty:
                st.info(f"選択されたカテゴリ '{selected_category_study}' には用語がありません。")
            else:
                current_term_index_key = f"current_term_index_{selected_category_study}"
                if current_term_index_key not in st.session_state:
                    st.session_state[current_term_index_key] = 0

                current_index = st.session_state[current_term_index_key] % len(filtered_df)
                current_term = filtered_df.iloc[current_index]

                st.subheader(f"用語: {current_term['用語 (Term)']}")
                st.markdown(f"**カテゴリ:** {current_term['カテゴリ (Category)']}")
                st.markdown(f"**学習進捗:** {current_term['学習進捗 (Progress)']}")
                
                show_details = st.checkbox("説明と例文を表示", key=f"show_details_study_{current_term['ID']}")
                if show_details:
                    st.info(f"**説明:** {current_term['説明 (Definition)']}")
                    if current_term['例文 (Example)']:
                        st.text(f"**例文:** {current_term['例文 (Example)']}")
                    else:
                        st.text("**例文:** (なし)")
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("前の用語", key="prev_term"):
                        st.session_state[current_term_index_key] -= 1
                        st.rerun()
                with col2:
                    if st.button("次の用語", key="next_term"):
                        st.session_state[current_term_index_key] += 1
                        st.rerun()
                with col3:
                    if st.button("ランダムな用語", key="random_term"):
                        st.session_state[current_term_index_key] = random.randint(0, len(filtered_df) - 1)
                        st.rerun()
    
    elif st.session_state.current_page == "テストモード":
        st.header("📝 テストモード")
        st.write("ビジネス用語の理解度をテストします。")

        if df_vocab.empty:
            st.info("まだ用語が登録されていません。サイドバーから新しい用語を追加してください。")
            st.session_state.test_mode['active'] = False
        elif len(df_vocab) < 5:
            st.info("テストを開始するには、最低5つの用語が必要です。")
            st.session_state.test_mode['active'] = False
        else:
            if not st.session_state.test_mode['active']:
                st.subheader("テスト設定")
                categories = df_vocab['カテゴリ (Category)'].dropna().unique().tolist()
                
                st.session_state.test_mode['selected_category'] = st.selectbox(
                    "テストカテゴリを選択", ['全カテゴリ'] + categories, key="test_category_select")
                
                st.session_state.test_mode['question_count'] = st.slider(
                    "出題数", min_value=5, max_value=min(20, len(df_vocab)), value=min(10, len(df_vocab)), step=1)
                
                st.session_state.test_mode['test_type'] = st.radio(
                    "テスト形式", [('用語 → 説明', 'term_to_def'), ('例文 → 用語', 'example_to_term')],
                    format_func=lambda x: x[0], key="test_type_radio")[1]
                
                st.session_state.test_mode['question_source'] = st.radio(
                    "出題元", [('ランダム', 'random_all'), ('学習中の用語', 'learning_focus')],
                    format_func=lambda x: x[0], key="question_source_radio")[1]

                if st.button("テスト開始", key="start_test"):
                    st.session_state.test_mode['active'] = True
                    st.session_state.test_mode['current_question_index'] = 0
                    st.session_state.test_mode['answers'] = []
                    st.session_state.test_mode['score'] = 0
                    st.session_state.test_mode['detailed_results'] = []
                    generate_questions()
                    st.rerun()
            else:
                display_test_questions()

    elif st.session_state.current_page == "テスト結果":
        st.header("📈 テスト結果")
        st.write("過去のテスト結果履歴を確認できます。")

        if df_test_results.empty:
            st.info("まだテスト結果がありません。テストモードでテストを実行してください。")
        else:
            st.subheader("テスト結果履歴")
            
            # プレビュー表示用のDataFrameを作成
            display_df_test_results = df_test_results.copy()
            # Detailsカラムは表示用に「詳細を見る」ボタンに置き換える（エラー回避のため一時的にコメントアウトまたはTextColumnに変更）
            # Streamlitのバージョンが古い場合はButtonColumnが使えないため
            # display_df_test_results['Details'] = ['詳細を見る'] * len(display_df_test_results)
            
            # === ButtonColumn を使用しない場合のフォールバック ===
            # Streamlitのバージョンが 1.26.0 未満の場合、ButtonColumnは存在しません。
            # そのため、代わりに通常のTextColumnとして表示するか、
            # 詳細表示用のselectboxと連携させる方法を推奨します。
            # 以下は一旦TextColumnとして表示する例です。
            
            st.dataframe(
                display_df_test_results,
                column_config={
                    "Date": st.column_config.DatetimeColumn("日付", format="YYYY/MM/DD HH:mm"),
                    "Category": "カテゴリ",
                    "TestType": "テスト形式",
                    "Score": "スコア",
                    "TotalQuestions": "出題数",
                    # "Details": st.column_config.ButtonColumn("詳細", help="テスト結果の詳細を表示します", width="small") # エラー回避のためコメントアウト
                    "Details": st.column_config.TextColumn("詳細", help="各問題の詳細データ (ここではJSON文字列)"), # 代替
                },
                hide_index=True,
                use_container_width=True
            )

            st.markdown("---")
            st.subheader("選択したテスト結果の詳細")
            if not df_test_results.empty:
                test_dates = df_test_results['Date'].dt.strftime('%Y/%m/%d %H:%M:%S').tolist()
                selected_test_index = st.selectbox("表示するテスト結果を選択", range(len(test_dates)), format_func=lambda x: f"{test_dates[x]} ({df_test_results.loc[x, 'Category']})", key="select_test_for_details")
                
                if selected_test_index is not None:
                    selected_test_data = df_test_results.iloc[selected_test_index]
                    
                    st.write(f"**日付:** {selected_test_data['Date'].strftime('%Y/%m/%d %H:%M:%S')}")
                    st.write(f"**カテゴリ:** {selected_test_data['Category']}")
                    st.write(f"**テスト形式:** {selected_test_data['TestType']}")
                    st.write(f"**最終スコア:** {selected_test_data['Score']} / {selected_test_data['TotalQuestions']}")
                    
                    st.markdown("---")
                    st.subheader("問題ごとの詳細")
                    if selected_test_data['Details']:
                        for i, detail in enumerate(selected_test_data['Details']):
                            st.markdown(f"**--- 問題 {i+1} ---**")
                            st.markdown(f"**用語:** {detail.get('term_name', 'N/A')}")
                            st.markdown(f"**問題文:** {detail.get('question_text', 'N/A')}")
                            st.markdown(f"**正解:** {detail.get('correct_answer', 'N/A')}")
                            st.markdown(f"**あなたの回答:** {detail.get('user_answer', 'N/A')}")
                            if detail.get('is_correct'):
                                st.success("正解！")
                            else:
                                st.error("不正解...")
                            st.markdown("")
                    else:
                        st.info("このテスト結果には詳細な問題データがありません。")
            else:
                st.info("表示できるテスト結果がありません。")


# --- テストモード関連関数 ---
def generate_questions():
    global df_vocab # df_vocabが更新される可能性があるのでglobalで参照

    filtered_df = df_vocab.copy()

    # カテゴリでフィルタリング
    if st.session_state.test_mode['selected_category'] != '全カテゴリ':
        filtered_df = filtered_df[
            filtered_df['カテゴリ (Category)'] == st.session_state.test_mode['selected_category']
        ]
    
    # 出題元でフィルタリング
    if st.session_state.test_mode['question_source'] == 'learning_focus':
        filtered_df = filtered_df[
            (filtered_df['学習進捗 (Progress)'] == 'Not Started') | 
            (filtered_df['学習進捗 (Progress)'] == 'Learning')
        ]
        if filtered_df.empty:
            st.warning("学習中の用語または未学習の用語が見つかりませんでした。ランダムな用語から出題します。")
            filtered_df = df_vocab.copy() # 全体から出題に戻す
            if st.session_state.test_mode['selected_category'] != '全カテゴリ':
                 filtered_df = filtered_df[
                    filtered_df['カテゴリ (Category)'] == st.session_state.test_mode['selected_category']
                ]
    
    if filtered_df.empty or len(filtered_df) < st.session_state.test_mode['question_count']:
        st.warning(f"指定された条件（カテゴリ: {st.session_state.test_mode['selected_category']}、出題元: {st.session_state.test_mode['question_source']}）に合う十分な用語が見つかりませんでした。全カテゴリからランダムに {st.session_state.test_mode['question_count']} 問出題します。")
        # df_vocabが空の場合にsampleを呼ぶとエラーになるのでチェック
        if df_vocab.empty:
            st.error("用語が登録されていません。テストを開始できません。")
            st.session_state.test_mode['active'] = False
            return
        filtered_df = df_vocab.sample(n=min(len(df_vocab), st.session_state.test_mode['question_count']), random_state=random.randint(0, 10000))
    else:
        filtered_df = filtered_df.sample(n=st.session_state.test_mode['question_count'], random_state=random.randint(0, 10000))


    questions_list = []
    
    for _, row in filtered_df.iterrows():
        options = []
        correct_answer = ""
        question_text = ""

        if st.session_state.test_mode['test_type'] == 'term_to_def':
            question_text = f"'{row['用語 (Term)']}' の説明として正しいものを選びなさい。"
            correct_answer = row['説明 (Definition)']
            # 間違った選択肢を生成 (正解以外の説明からランダムに選ぶ)
            wrong_options_df = df_vocab[
                (df_vocab['ID'] != row['ID']) & 
                (df_vocab['説明 (Definition)'].notna()) & 
                (df_vocab['説明 (Definition)'] != correct_answer)
            ]
            if len(wrong_options_df) >= 3:
                wrong_answers = wrong_options_df.sample(n=3)['説明 (Definition)'].tolist()
            else:
                wrong_answers = wrong_options_df['説明 (Definition)'].tolist()
                # 足りない分は他の用語の説明で埋める（ユニーク性を考慮）
                while len(wrong_answers) < 3 and len(df_vocab) > len(wrong_answers) + 1: # 無限ループ防止
                    additional_def = df_vocab.sample(n=1)['説明 (Definition)'].iloc[0]
                    if additional_def not in options and additional_def != correct_answer:
                        wrong_answers.append(additional_def)
                while len(wrong_answers) < 3: #それでも足りなければダミー
                    wrong_answers.append(f"ダミーの説明 {len(wrong_answers) + 1}")
            
            options = [correct_answer] + wrong_answers
            random.shuffle(options)

        elif st.session_state.test_mode['test_type'] == 'example_to_term':
            if pd.isna(row['例文 (Example)']) or not row['例文 (Example)'].strip():
                # 例文がない場合はスキップするか、別の問題タイプにフォールバックする
                # ここではスキップして、出題数を満たさない場合は警告を出す
                continue 

            question_text = f"以下の例文が指す用語として正しいものを選びなさい。\n\n「{row['例文 (Example)'][:-1]}。」" # 語尾調整
            correct_answer = row['用語 (Term)']
            # 間違った選択肢を生成 (正解以外の用語からランダムに選ぶ)
            wrong_options_df = df_vocab[
                (df_vocab['ID'] != row['ID']) & 
                (df_vocab['用語 (Term)'].notna()) & 
                (df_vocab['用語 (Term)'] != correct_answer)
            ]
            if len(wrong_options_df) >= 3:
                wrong_answers = wrong_options_df.sample(n=3)['用語 (Term)'].tolist()
            else:
                wrong_answers = wrong_options_df['用語 (Term)'].tolist()
                # 足りない分は他の用語名で埋める（ユニーク性を考慮）
                while len(wrong_answers) < 3 and len(df_vocab) > len(wrong_answers) + 1: # 無限ループ防止
                    additional_term = df_vocab.sample(n=1)['用語 (Term)'].iloc[0]
                    if additional_term not in options and additional_term != correct_answer:
                        wrong_answers.append(additional_term)
                while len(wrong_answers) < 3: #それでも足りなければダミー
                    wrong_answers.append(f"ダミー用語 {len(wrong_answers) + 1}")

            options = [correct_answer] + wrong_answers
            random.shuffle(options)
        
        # オプションが空または少なすぎる場合のチェック
        if not options or len(options) < 2:
            st.warning(f"用語 '{row['用語 (Term)']}' の問題生成に失敗しました (選択肢が不足)。この問題はスキップされます。")
            continue

        questions_list.append({
            'term_id': row['ID'],
            'term_name': row['用語 (Term)'],
            'term_definition': row['説明 (Definition)'],
            'term_example': row['例文 (Example)'],
            'question_text': question_text,
            'options': options,
            'correct_answer': correct_answer
        })
    
    # 最終的な出題数が設定数より少ない場合
    if len(questions_list) < st.session_state.test_mode['question_count']:
        st.warning(f"選択された条件で{st.session_state.test_mode['question_count']}問を生成できませんでした。{len(questions_list)}問が出題されます。")
    
    st.session_state.test_mode['questions'] = questions_list
    st.session_state.test_mode['answers'] = [None] * len(questions_list)

def display_test_questions():
    questions = st.session_state.test_mode['questions']
    current_index = st.session_state.test_mode['current_question_index']

    if current_index >= len(questions):
        # 全問終了、結果表示
        st.subheader("テスト結果")
        st.write(f"お疲れ様でした！ あなたの最終スコアは {st.session_state.test_mode['score']}/{len(questions)} です。")
        
        save_test_results_and_progress() # 結果と進捗を保存
        st.session_state.test_mode['active'] = False # テストモードを終了
        
        if st.button("もう一度テストする", key="retake_test"):
            st.session_state.test_mode['active'] = False # 設定画面に戻る
            st.rerun()
        if st.button("結果を詳細に確認する (テスト結果ページへ)", key="go_to_test_results"):
            go_to_page("テスト結果")
        return

    question = questions[current_index]

    st.subheader(f"問題 {current_index + 1} / {len(questions)}")
    st.markdown(question['question_text'])

    # 選択肢の表示
    user_answer = st.radio(
        "選択肢", 
        question['options'], 
        key=f"question_{current_index}",
        index=question['options'].index(st.session_state.test_mode['answers'][current_index]) if st.session_state.test_mode['answers'][current_index] in question['options'] else None
    )
    st.session_state.test_mode['answers'][current_index] = user_answer

    col1, col2 = st.columns(2)
    with col1:
        if current_index > 0 and st.button("前の問題", key="prev_question"):
            st.session_state.test_mode['current_question_index'] -= 1
            st.rerun()
    with col2:
        if st.button("次の問題", key="next_question_or_finish"):
            st.session_state.test_mode['current_question_index'] += 1
            st.rerun()


# --- テスト結果と学習進捗をGASに書き込む関数 ---
def save_test_results_and_progress():
    global df_vocab, df_test_results # グローバル変数として宣言

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
            else: # 不正解の場合
                if current_progress == 'Mastered': # MasteredからLearningに戻す
                    df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Learning'
                # LearningやNot Startedの場合は変更しない (またはNot Startedに戻すロジックもありうる)
                elif current_progress == 'Learning':
                    df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Not Started' # LearningからNot Startedに戻す
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

    # df_test_resultsがまだ空の場合はヘッダーを先に作成 (これはロード時に行われるべきだが念のため)
    if df_test_results.empty and not st.session_state.df_test_results.empty:
         df_test_results = st.session_state.df_test_results # セッションステートから取得
    elif df_test_results.empty: # まだ空の場合は初期化
        df_test_results = pd.DataFrame(columns=TEST_RESULTS_HEADERS)


    # 新しい結果を行として追加
    new_result_row_data = {
        'Date': test_date_obj,
        'Category': category_used,
        'TestType': test_type_display,
        'Score': final_score,
        'TotalQuestions': len(questions),
        'Details': current_detailed_results # ここはjson.dumpsせず生のリストオブジェクトのまま
    }
    # pandas.concatの代わりに_appendを使用 (将来のバージョンでのwarning回避のため)
    df_test_results = df_test_results._append(new_result_row_data, ignore_index=True)
    st.session_state.df_test_results = df_test_results # セッションステートも更新

    # write_data_to_gasにDataFrame全体を渡す
    # write_data_to_gas内でDetailsカラムのjson.dumpsが適用される
    write_success_results = write_data_to_gas(df_test_results, test_results_sheet_name)

    if write_success_results:
        st.success("テスト結果が保存されました！「テスト結果」ページから確認できます。")
    else:
        st.error("テスト結果の保存に失敗しました。")

    if updated_vocab_ids:
        write_success_vocab = write_data_to_gas(df_vocab, current_worksheet_name)
        if write_success_vocab:
            st.success("学習進捗が更新されました！")
            st.session_state.df_vocab = df_vocab # セッションステートも更新
        else:
            st.error("学習進捗の更新に失敗しました。")
