import streamlit as st
import pandas as pd
# requestsとjsonはGASを使わない場合は不要だが、汎用性のため残す
import requests
import json
import os
import random
from datetime import datetime, date
import io

# --- Supabase 接続のインポート ---
# ★★★ この行がエラーの原因なので、ここがimportできるようになるのが目標 ★★★
from st_supabase_connection import SupabaseConnection

# --- 設定項目 ---
# GASのURLとキーはSupabase移行に伴い不要になるため削除
# GAS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbzIHdzvPWRgu3uyOb2A1rHQTvpxzU6sLKBm5Ybwt--ozxLFe0_i7nr071RjwjgdkaxGA/exec"
# GAS_API_KEY = "my_streamlit_secret_key_123"

# ヘッダー定義
VOCAB_HEADERS = ['ID', '用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)', '学習進捗 (Progress)']
TEST_RESULTS_HEADERS = ['Date', 'Category', 'TestType', 'Score', 'TotalQuestions', 'Details']

# --- Streamlit アプリケーションの開始 ---
st.set_page_config(layout="wide")
st.title("ビジネス用語集ビルダー")

# --- ページ遷移関数 ---
def go_to_page(page_name):
    st.session_state.current_page = page_name
    st.rerun()

# st.session_state の初期化
if 'username' not in st.session_state:
    st.session_state.username = None
if 'current_page' not in st.session_state:
    st.session_state.current_page = "用語集" # デフォルトページを用語集に変更
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


# --- Supabase 接続の初期化 (st.secrets から認証情報を取得) ---
@st.cache_resource
def get_supabase_connection():
    # st.secrets から安全に認証情報を取得
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")

    if not url or not key:
        st.error("Supabaseの認証情報が見つかりません。Streamlit CloudのSecretsまたは.streamlit/secrets.tomlにSUPABASE_URLとSUPABASE_KEYを設定してください。")
        st.stop() # 処理を停止してエラーを表示

    return st.connection("supabase", type=SupabaseConnection, url=url, key=key)

supabase = get_supabase_connection()


# --- Supabaseからデータをロードする関数 (GAS版からの変更) ---
@st.cache_data(ttl=60)
def load_data_from_supabase(table_name):
    st.sidebar.write(f"DEBUG: Attempting to load data from Supabase table: {table_name}")
    try:
        # Supabaseから全データを読み込む
        response = supabase.table(table_name).select("*").execute()
        
        if response.data:
            df = pd.DataFrame(response.data)
            st.sidebar.write(f"DEBUG: Successfully loaded {len(df)} rows from table '{table_name}'.")

            if table_name.startswith("vocab_"): # 用語シートの場合
                # 必要なカラムが存在しない場合に作成（インポート時のエラー回避）
                for col in VOCAB_HEADERS:
                    if col not in df.columns:
                        df[col] = pd.NA
                df = df[VOCAB_HEADERS] # カラム順序を固定
                
                df['ID'] = pd.to_numeric(df['ID'], errors='coerce').fillna(0).astype('Int64')
                df['学習進捗 (Progress)'] = df['学習進捗 (Progress)'].fillna('Not Started')
                df['例文 (Example)'] = df['例文 (Example)'].fillna('')
                df = df.dropna(subset=['用語 (Term)', '説明 (Definition)'], how='all') # 両方NaNの行を削除
                df = df.drop_duplicates(subset=['用語 (Term)', '説明 (Definition)'], keep='first') # 重複行を削除
                df = df.sort_values(by='ID').reset_index(drop=True)
                
            elif table_name.startswith("test_results_"): # テスト結果シートの場合
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
                            # Supabaseからのデータは既に辞書/リストの場合もあるため、直接返す
                            # 文字列の場合はjson.loadsを試みる
                            if isinstance(json_str, (dict, list)):
                                return json_str
                            return json.loads(json_str)
                        except (json.JSONDecodeError, TypeError):
                            st.warning(f"テスト結果の詳細データをJSONとしてパースできませんでした: {str(json_str)[:200]}...")
                            return []
                    df['Details'] = df['Details'].apply(parse_json_safely)
                else:
                    df['Details'] = [[] for _ in range(len(df))]
            
            return df
        else:
            st.sidebar.write(f"DEBUG: No data found in table '{table_name}'. Returning empty DataFrame.")
            return pd.DataFrame(columns=TEST_RESULTS_HEADERS if table_name.startswith("test_results_") else VOCAB_HEADERS)

    except Exception as e:
        st.error(f"Supabaseからのデータの読み込み中にエラーが発生しました: {e}")
        st.exception(e)
        st.sidebar.write(f"DEBUG: Supabase Read Error: {e}")
        return pd.DataFrame(columns=TEST_RESULTS_HEADERS if table_name.startswith("test_results_") else VOCAB_HEADERS)


# --- Supabaseにデータを書き込む関数 (GAS版からの変更) ---
def write_data_to_supabase(df, table_name):
    try:
        # Supabaseに送るデータはPythonのリストオブ辞書形式
        # Pandas DataFrameをJSON形式に変換する前に、DateTimeオブジェクトをISOフォーマットに変換する必要がある
        data_to_upsert = df.to_dict(orient='records')
        
        # Detailsカラムの処理（SupabaseはJSONB型で格納するため、そのままPythonのリスト/辞書として渡す）
        # to_dict(orient='records')はデフォルトでこれを適切に処理するはず

        # Upsert (存在すれば更新、なければ挿入) を使用
        # Supabaseのテーブルには主キー（通常はID）があることを前提とする
        # IDが自動生成の場合は、IDを無視してinsertする
        
        # まずは既存のレコードをすべて削除し、新しいデータを挿入する方式で実装
        # これはデータ量が少ない場合にのみ適しており、大規模データでは非効率
        # 理想的には、変更された行のみを更新、削除された行を削除、追加された行を挿入する
        
        # 簡単のために、今回は「全削除＆全挿入」で実装
        # 実際には、IDを基にupdate/insertを使い分けるか、upsertを使うのが良い
        # `supabase.table(table_name).upsert(data_to_upsert, on_conflict='ID').execute()`
        
        # ここではまずシンプルなdelete().execute() & insert().execute()を試す
        
        # 既存データを全削除
        st.sidebar.write(f"DEBUG: Deleting all existing data from table '{table_name}'...")
        delete_response = supabase.table(table_name).delete().neq('ID', -1).execute() # ID=-1は存在しないと仮定
        # .execute()の戻り値はdata, count, status_codeなどを含むオブジェクト
        if delete_response.data is None: # Supabase client >= 2.0.0
             st.sidebar.write(f"DEBUG: Successfully cleared table '{table_name}'.")
        else: # Supabase client < 2.0.0 (old behavior, data might contain deleted rows)
            st.sidebar.write(f"DEBUG: Successfully cleared table '{table_name}'. Deleted {len(delete_response.data)} rows.")

        # 新しいデータを挿入
        st.sidebar.write(f"DEBUG: Inserting {len(data_to_upsert)} rows into table '{table_name}'...")
        insert_response = supabase.table(table_name).insert(data_to_upsert).execute()
        
        if insert_response.data:
            st.cache_data.clear() # キャッシュをクリアして、次回の読み込みで最新データを取得させる
            st.sidebar.write(f"DEBUG: Data successfully written to Supabase table '{table_name}'.")
            return True
        else:
            st.error(f"Supabaseへの書き込み中にエラーが発生しました。レスポンス: {insert_response}")
            st.sidebar.write(f"DEBUG: Supabase Write Error Response: {insert_response}")
            return False

    except Exception as e:
        st.error(f"Supabaseへのデータの書き込み中に予期せぬエラーが発生しました: {e}")
        st.exception(e)
        st.sidebar.write(f"DEBUG: Unexpected Supabase Write Error: {e}")
        return False


# --- メインロジック ---

# ユーザー名に応じたテーブル名の設定 (usernameがNoneの場合は一時的なデフォルト)
# Supabaseのテーブル名は小文字推奨、ハイフンではなくアンダースコア推奨
# `vocab_`と`test_results_`というプレフィックスを付ける
current_vocab_table_name = f"vocab_{st.session_state.username.lower()}" if st.session_state.username else "vocab_default"
current_test_results_table_name = f"test_results_{st.session_state.username.lower()}" if st.session_state.username else "test_results_default"


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
            # ユーザー名が設定されたので、関連するテーブル名も更新
            current_vocab_table_name = f"vocab_{st.session_state.username.lower()}"
            current_test_results_table_name = f"test_results_{st.session_state.username.lower()}"
            # 新しいユーザー名でデータをロードし直す
            with st.spinner(f"{st.session_state.username}さんのデータをロード中..."):
                # Supabaseからデータをロード
                st.session_state.df_vocab = load_data_from_supabase(current_vocab_table_name)
                st.session_state.df_test_results = load_data_from_supabase(current_test_results_table_name)
                st.session_state.vocab_data_loaded = True
            # ログイン後、用語集へ
            st.session_state.current_page = "用語集"
            st.rerun()
else: # ユーザーがログインしている場合
    # ユーザー名が設定されているが、データがまだロードされていない場合はロードする
    if not st.session_state.vocab_data_loaded:
        with st.spinner(f"{st.session_state.username}さんのデータをロード中..."):
            # Supabaseからデータをロード
            st.session_state.df_vocab = load_data_from_supabase(current_vocab_table_name)
            st.session_state.df_test_results = load_data_from_supabase(current_test_results_table_name)
            st.session_state.vocab_data_loaded = True
    
    # ここからはセッションステートからDataFrameを取得して使用
    df_vocab = st.session_state.df_vocab
    df_test_results = st.session_state.df_test_results

    # --- 共通サイドバー ---
    st.sidebar.title(f"ようこそ、{st.session_state.username}さん！")
    
    # ページ選択ボタン
    if st.sidebar.button("📝 用語集", key="nav_vocab_list"):
        go_to_page("用語集")
    if st.sidebar.button("📊 データ管理", key="nav_data_management"):
        go_to_page("データ管理")
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
            if new_term and new_definition and new_category and new_category != '新しいカテゴリを作成': 
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
                # Supabaseに書き込む
                if write_data_to_supabase(df_vocab, current_vocab_table_name):
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
        st.session_state.df_vocab = pd.DataFrame(columns=VOCAB_HEADERS)
        st.session_state.df_test_results = pd.DataFrame(columns=TEST_RESULTS_HEADERS)
        st.rerun()

    # --- メインコンテンツ ---
    if st.session_state.current_page == "用語集":
        st.header("📝 用語集")
        st.write("登録されているビジネス用語を検索・閲覧できます。")

        if df_vocab.empty:
            st.info("まだ用語が登録されていません。サイドバーから新しい用語を追加してください。")
        else:
            # 検索とフィルタリングのUI
            col_search, col_category = st.columns([2, 1])
            with col_search:
                search_query = st.text_input("キーワード検索 (用語、説明、例文、カテゴリ)", key="vocab_search_query")
            with col_category:
                categories = ['全カテゴリ'] + df_vocab['カテゴリ (Category)'].dropna().unique().tolist()
                selected_category_filter = st.selectbox("カテゴリで絞り込み", categories, key="vocab_category_filter")

            filtered_vocab = df_vocab.copy()

            # カテゴリフィルタリング
            if selected_category_filter != '全カテゴリ':
                filtered_vocab = filtered_vocab[filtered_vocab['カテゴリ (Category)'] == selected_category_filter]

            # 文字検索 (あいまい検索)
            if search_query:
                search_cols = ['用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)']
                filtered_vocab = filtered_vocab[
                    filtered_vocab[search_cols].astype(str).apply(
                        lambda x: x.str.contains(search_query, case=False, na=False)
                    ).any(axis=1)
                ]
            
            if filtered_vocab.empty:
                st.info("条件に一致する用語は見つかりませんでした。")
            else:
                st.dataframe(
                    filtered_vocab.set_index('ID'),
                    column_order=['用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)', '学習進捗 (Progress)'],
                    use_container_width=True
                )

    elif st.session_state.current_page == "データ管理":
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
                required_cols = ['用語 (Term)', '説明 (Definition)', 'カテゴリ (Category)']
                if edited_df[required_cols].isnull().values.any() or (edited_df[required_cols] == '').any().any():
                    st.error("用語、説明、カテゴリは必須です。空欄がないか確認してください。")
                    st.stop()
                else:
                    # 'ID'がNaNになっている新規行を特定し、IDを付与
                    new_rows = edited_df[edited_df['ID'].isna()]
                    for idx, row in new_rows.iterrows():
                        next_id = (df_vocab['ID'].max() + 1) if not df_vocab.empty else 1
                        edited_df.loc[idx, 'ID'] = next_id
                    
                    # edited_dfをdf_vocabに代入し、Supabaseに書き込む
                    df_vocab = edited_df.astype({'ID': 'Int64'})
                    if write_data_to_supabase(df_vocab, current_vocab_table_name):
                        st.success("変更を保存しました！")
                        st.session_state.df_vocab = df_vocab # セッションステートも更新
                        st.rerun()
                    else:
                        st.error("変更の保存に失敗しました。")

        st.markdown("---")
        st.subheader("データのインポート / エクスポート")

        # --- エクスポート ---
        st.markdown("##### データのエクスポート")
        csv_data = df_vocab.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="CSVとしてエクスポート",
            data=csv_data,
            file_name=f"vocab_data_{st.session_state.username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            key="export_csv"
        )
        
        json_data = df_vocab.to_json(orient="records", force_ascii=False)
        st.download_button(
            label="JSONとしてエクスポート",
            data=json_data,
            file_name=f"vocab_data_{st.session_state.username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            key="export_json"
        )

        # --- インポート ---
        st.markdown("##### データのインポート")
        uploaded_file = st.file_uploader("CSVまたはJSONファイルをアップロード", type=["csv", "json"], key="import_file_uploader")

        if uploaded_file is not None:
            import_action = st.radio(
                "インポート方法を選択",
                ("既存データに追加", "既存データを上書き"),
                key="import_action_radio"
            )
            
            if st.button("インポートを実行", key="execute_import"):
                try:
                    if uploaded_file.name.endswith('.csv'):
                        imported_df = pd.read_csv(uploaded_file)
                    elif uploaded_file.name.endswith('.json'):
                        imported_df = pd.read_json(uploaded_file)
                    else:
                        st.error("サポートされていないファイル形式です。CSVまたはJSONファイルをアップロードしてください。")
                        st.stop()
                    
                    # 必要なカラムが存在するかチェック
                    missing_cols = [col for col in VOCAB_HEADERS if col not in imported_df.columns]
                    if missing_cols:
                        st.warning(f"アップロードされたファイルには以下の必須カラムが不足しています: {', '.join(missing_cols)}。これらのカラムは空として追加されます。")
                        for col in missing_cols:
                            imported_df[col] = pd.NA
                    imported_df = imported_df[VOCAB_HEADERS]

                    if import_action == "既存データを上書き":
                        df_vocab = imported_df.copy()
                        # IDは全て振り直し
                        df_vocab['ID'] = range(1, len(df_vocab) + 1)
                        df_vocab['ID'] = df_vocab['ID'].astype('Int64')
                        st.warning("既存のデータは全て上書きされます。")
                    else: # 既存データに追加
                        # 既存のIDの最大値を取得し、新しいIDを付与
                        max_id = df_vocab['ID'].max() if not df_vocab.empty else 0
                        
                        # インポートデータのIDを振り直し（重複やNaN対策）
                        imported_df['ID'] = imported_df.apply(
                            lambda row: max_id + 1 + imported_df.index.get_loc(row.name) if pd.isna(row['ID']) or row['ID'] == 0 else row['ID'], axis=1
                        )
                        # 既存データとIDが重複しないように調整
                        if not df_vocab.empty:
                            existing_ids = df_vocab['ID'].dropna().astype(int).tolist()
                            imported_df['ID'] = imported_df['ID'].apply(lambda x: x if x not in existing_ids else max_id + 1 + imported_df[imported_df['ID']==x].index[0])
                        
                        # 最終的なIDを再度一意に調整（念のため）
                        all_ids = list(df_vocab['ID'].dropna().astype(int)) if not df_vocab.empty else []
                        for i in range(len(imported_df)):
                            if imported_df.loc[i, 'ID'] in all_ids:
                                imported_df.loc[i, 'ID'] = max(all_ids) + 1
                            all_ids.append(int(imported_df.loc[i, 'ID']))
                        
                        df_vocab = pd.concat([df_vocab, imported_df], ignore_index=True)
                        df_vocab['ID'] = df_vocab['ID'].astype('Int64') # 型を合わせる
                        st.info("既存データに追加されます。")
                    
                    df_vocab = df_vocab.drop_duplicates(subset=['用語 (Term)', '説明 (Definition)'], keep='first')
                    df_vocab = df_vocab.sort_values(by='ID').reset_index(drop=True)

                    if write_data_to_supabase(df_vocab, current_vocab_table_name):
                        st.success("データのインポートに成功しました！")
                        st.session_state.df_vocab = df_vocab # セッションステートも更新
                        st.rerun()
                    else:
                        st.error("データのインポートに失敗しました。")

                except Exception as e:
                    st.error(f"ファイルのインポート中にエラーが発生しました: {e}")
                    st.exception(e)
        
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
