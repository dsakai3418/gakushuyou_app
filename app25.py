import streamlit as st
import pandas as pd
import requests
import json
import os
import random
from datetime import datetime, date
import io

# --- Supabase 接続のインポート ---
from st_supabase_connection import SupabaseConnection

# --- 設定項目 ---
VOCAB_HEADERS = ['ID', '用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)', '学習進捗 (Progress)']
TEST_RESULTS_HEADERS = ['Date', 'Category', 'TestType', 'Score', 'TotalQuestions', 'Details']

# --- Streamlit アプリケーションの開始 ---
st.set_page_config(layout="wide")
st.title("ビジネス用語集ビルダー")

# st.session_state の初期化
if 'username' not in st.session_state:
    st.session_state.username = None
if 'current_page' not in st.session_state:
    st.session_state.current_page = "用語集"
if 'vocab_data_loaded' not in st.session_state:
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
if 'df_vocab' not in st.session_state:
    st.session_state.df_vocab = pd.DataFrame(columns=VOCAB_HEADERS)
if 'df_test_results' not in st.session_state:
    st.session_state.df_test_results = pd.DataFrame(columns=TEST_RESULTS_HEADERS)


# --- Supabase 接続の初期化 (st.secrets から認証情報を取得) ---
@st.cache_resource
def get_supabase_connection():
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")

    if not url or not key:
        st.error("Supabaseの認証情報が見つかりません。Streamlit CloudのSecretsまたは.streamlit/secrets.tomlにSUPABASE_URLとSUPABASE_KEYを設定してください。")
        st.stop()

    return st.connection("supabase", type=SupabaseConnection, url=url, key=key)

supabase = get_supabase_connection()

# --- テーブルが存在しない場合に自動で作成する関数 ---
# この関数は、Supabaseプロジェクトに public.execute_sql 関数が作成されていることを前提とします。
def create_table_if_not_exists(table_name, headers, is_vocab_table=True):
    st.sidebar.write(f"DEBUG: Checking for table '{table_name}'...")
    try:
        # テーブルが存在するか確認 (簡単なクエリを試す)
        # 存在しない場合、st-supabase-connectionはAPIErrorを発生させる
        supabase.table(table_name).select('ID').limit(0).execute()
        st.sidebar.write(f"DEBUG: Table '{table_name}' already exists.")
        return True
    except Exception as e:
        # テーブルが存在しない場合、エラー（PGRST205など）が発生する
        # APIErrorかどうかをチェックして、存在しない場合にのみ作成処理に進む
        if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code == 404: # 実際は404ではなくAPIErrorのコードをチェック
            st.sidebar.write(f"DEBUG: Table '{table_name}' does not exist (HTTP 404), creating it.")
        elif "PGRST205" in str(e): # PGRST205はPostgRESTがテーブルを見つけられないエラーコード
             st.sidebar.write(f"DEBUG: Table '{table_name}' does not exist (PGRST205), creating it.")
        else:
            st.sidebar.write(f"DEBUG: Unknown error when checking table '{table_name}': {e}. Attempting to create.")
        
        # テーブル作成クエリ
        if is_vocab_table:
            columns_sql = ", ".join([f'"{h}" text NULL' for h in headers if h != 'ID'])
            create_query = f"""
            CREATE TABLE public."{table_name}" (
                "ID" bigint NOT NULL,
                {columns_sql},
                CONSTRAINT "{table_name}_pkey" PRIMARY KEY ("ID")
            );
            """
        else: # test_results_ table
            create_query = f"""
            CREATE TABLE public."{table_name}" (
                "Date" timestamp with time zone NULL,
                "Category" text NULL,
                "TestType" text NULL,
                "Score" bigint NULL,
                "TotalQuestions" bigint NULL,
                "Details" jsonb NULL
            );
            """
        
        try:
            # SQLを実行してテーブルを作成 (RPC経由)
            st.sidebar.write(f"DEBUG: Executing create table query for '{table_name}'...")
            supabase.rpc("execute_sql", {'sql_query': create_query}).execute()
            st.sidebar.write(f"DEBUG: Successfully created table '{table_name}'.")

            # RLSポリシーも自動で追加 (開発用、本番では見直し推奨)
            # 全員にアクセスを許可するポリシー
            rls_policy_query = f"""
            CREATE POLICY "Enable all access for anon users on {table_name}"
            ON public."{table_name}"
            FOR ALL
            TO anon
            USING (TRUE)
            WITH CHECK (TRUE);
            """
            st.sidebar.write(f"DEBUG: Executing RLS policy query for '{table_name}'...")
            supabase.rpc("execute_sql", {'sql_query': rls_policy_query}).execute()
            st.sidebar.write(f"DEBUG: RLS policy added for table '{table_name}'.")
            return True
        except Exception as create_e:
            st.error(f"テーブル '{table_name}' の作成中にエラーが発生しました: {create_e}")
            st.exception(create_e)
            st.sidebar.write(f"DEBUG: Table creation error: {create_e}")
            return False

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
        data_to_upsert = df.to_dict(orient='records')
        
        # 既存データを全削除 (ID = -1 は存在しないと仮定して、全行を対象)
        st.sidebar.write(f"DEBUG: Deleting all existing data from table '{table_name}'...")
        # delete().neq('ID', -1) は、IDが-1でないすべての行を削除するという意図。
        # SupabaseのPythonクライアントで全削除するには、select('*').execute() でIDを取得してから削除するか、
        # あるいは RLS を考慮しないなら .delete().gt('ID', 0) などで全行対象にするのが確実。
        # ここでは一番シンプルな .delete().neq('ID', -1).execute() で行が返されることを期待する
        # .data が None でないことを確認して、成功を判断する
        delete_response = supabase.table(table_name).delete().neq('ID', -1).execute() 
        
        if delete_response.data is not None or delete_response.count >= 0: # 削除が正常に行われたと判断
             st.sidebar.write(f"DEBUG: Successfully cleared table '{table_name}'. Deleted {delete_response.count} rows.")
        else:
            st.warning(f"DEBUG: Could not confirm clearing table '{table_name}'. Response: {delete_response}")


        # 新しいデータを挿入
        st.sidebar.write(f"DEBUG: Inserting {len(data_to_upsert)} rows into table '{table_name}'...")
        insert_response = supabase.table(table_name).insert(data_to_upsert).execute()
        
        if insert_response.data: # 挿入されたデータが返されれば成功
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
current_vocab_table_name = f"vocab_{st.session_state.username.lower()}" if st.session_state.username else "vocab_default"
current_test_results_table_name = f"test_results_{st.session_state.username.lower()}" if st.session_state.username else "test_results_default"


# ユーザー名が設定されていない場合（ログイン前）は、ログインフォームを表示
if st.session_state.username is None:
    st.session_state.current_page = "Welcome"
    st.header("Welcome to ビジネス用語集ビルダー！")
    st.write("このアプリは、あなたのビジネス用語学習をサポートします。")
    st.markdown("詳しい使い方は、以下のページをご参照ください。")
    st.markdown("[使い方ガイド（Notion）](https://www.notion.so/tacoms/285383207704802ca7cdddc3a7b8271f)")
    st.info("最初にあなたの名前を入力してください。")
    with st.form("username_form_welcome_fallback"):
        input_username = st.text_input("あなたの名前を入力してください", key="login_username_input")
        submit_username = st.form_submit_button("進む")
        if submit_username and input_username:
            st.session_state.username = input_username
            # ユーザー名が設定されたので、関連するテーブル名も更新
            current_vocab_table_name = f"vocab_{st.session_state.username.lower()}"
            current_test_results_table_name = f"test_results_{st.session_state.username.lower()}"
            
            with st.spinner(f"{st.session_state.username}さんのテーブルとデータを準備中..."):
                # テーブル自動生成
                if not create_table_if_not_exists(current_vocab_table_name, VOCAB_HEADERS, is_vocab_table=True):
                    st.error("用語集テーブルの準備に失敗しました。")
                    st.session_state.username = None # 失敗したらログインをキャンセル
                    st.rerun()
                if not create_table_if_not_exists(current_test_results_table_name, TEST_RESULTS_HEADERS, is_vocab_table=False):
                    st.error("テスト結果テーブルの準備に失敗しました。")
                    st.session_state.username = None # 失敗したらログインをキャンセル
                    st.rerun()

                # 新しいユーザー名でデータをロードし直す
                st.session_state.df_vocab = load_data_from_supabase(current_vocab_table_name)
                st.session_state.df_test_results = load_data_from_supabase(current_test_results_table_name)
                st.session_state.vocab_data_loaded = True
            # ログイン後、用語集へ
            st.session_state.current_page = "用語集"
            st.rerun()
else: # ユーザーがログインしている場合
    # ユーザー名が設定されているが、データがまだロードされていない場合はロードする
    if not st.session_state.vocab_data_loaded:
        with st.spinner(f"{st.session_state.username}さんのテーブルとデータを準備中..."):
            # テーブル自動生成
            if not create_table_if_not_exists(current_vocab_table_name, VOCAB_HEADERS, is_vocab_table=True):
                st.error("用語集テーブルの準備に失敗しました。")
                st.session_state.username = None # 失敗したらログインをキャンセル
                st.rerun()
            if not create_table_if_not_exists(current_test_results_table_name, TEST_RESULTS_HEADERS, is_vocab_table=False):
                st.error("テスト結果テーブルの準備に失敗しました。")
                st.session_state.username = None # 失敗したらログインをキャンセル
                st.rerun()

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
                    "問題数", min_value=5, max_value=len(df_vocab), value=min(10, len(df_vocab)), step=1, key="test_question_count_slider")
                
                st.session_state.test_mode['test_type'] = st.radio(
                    "テスト形式",
                    [('用語から説明を選ぶ', 'term_to_def'),
                     ('例文から用語を選ぶ', 'example_to_term')],
                    format_func=lambda x: x[0], key="test_type_radio"
                )[1] # タプルの2番目の要素（キー）を取得
                
                st.session_state.test_mode['question_source'] = st.radio(
                    "出題元",
                    [('ランダム (全用語から)', 'random_all'),
                     ('学習不足用語から優先的に', 'learning_focus')],
                    format_func=lambda x: x[0], key="test_source_radio"
                )[1]

                if st.button("テスト開始", key="start_test_button"):
                    start_new_test(df_vocab)
            else:
                run_test(df_vocab, current_test_results_table_name)

    elif st.session_state.current_page == "テスト結果":
        st.header("📈 テスト結果")
        st.write("過去のテスト結果を閲覧できます。")

        if df_test_results.empty:
            st.info("まだテスト結果がありません。テストモードで学習を開始しましょう！")
        else:
            # テスト結果の概要表示
            st.subheader("テスト結果一覧")
            display_df_test_results = df_test_results.copy()
            # 表示用のカラムを選択し、必要であればフォーマット
            display_df_test_results['Date'] = display_df_test_results['Date'].dt.strftime('%Y-%m-%d %H:%M')
            st.dataframe(
                display_df_test_results[['Date', 'Category', 'TestType', 'Score', 'TotalQuestions']],
                use_container_width=True,
                hide_index=True
            )

            # 詳細レビュー機能
            st.subheader("テスト結果の詳細レビュー")
            if len(df_test_results) > 0:
                result_dates = df_test_results['Date'].dt.strftime('%Y-%m-%d %H:%M').tolist()
                selected_result_index = st.selectbox("レビューするテスト結果を選択", range(len(result_dates)),
                                                     format_func=lambda x: result_dates[x], key="review_select_result")
                
                if st.button("このテスト結果をレビュー", key="start_review_button"):
                    st.session_state.test_review_mode['active'] = True
                    st.session_state.test_review_mode['review_index'] = 0
                    st.session_state.test_review_mode['results_to_review'] = df_test_results.loc[selected_result_index, 'Details']
                    go_to_page("テスト結果") # 現在のページをリロードしてレビュー表示を開始
            
            if st.session_state.test_review_mode['active']:
                review_current_question = st.session_state.test_review_mode['results_to_review'][st.session_state.test_review_mode['review_index']]
                
                st.markdown(f"#### 問題 {st.session_state.test_review_mode['review_index'] + 1} / {len(st.session_state.test_review_mode['results_to_review'])}")
                
                st.write(f"**出題:** {review_current_question['question_text']}")
                st.write(f"**正解:** {review_current_question['correct_answer']}")
                st.write(f"**あなたの回答:** {review_current_question['user_answer']}")
                
                if review_current_question['is_correct']:
                    st.success("✅ 正解")
                else:
                    st.error("❌ 不正解")
                
                st.markdown("---")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.session_state.test_review_mode['review_index'] > 0:
                        if st.button("⬅️ 前の問題", key="prev_review_question"):
                            st.session_state.test_review_mode['review_index'] -= 1
                            st.rerun()
                with col2:
                    if st.session_state.test_review_mode['review_index'] < len(st.session_state.test_review_mode['results_to_review']) - 1:
                        if st.button("次の問題 ➡️", key="next_review_question"):
                            st.session_state.test_review_mode['review_index'] += 1
                            st.rerun()
                    else:
                        st.info("すべての問題のレビューが完了しました。")
                        if st.button("レビューを終了", key="end_review_mode"):
                            st.session_state.test_review_mode['active'] = False
                            st.rerun()

    else: # Welcomeページ (ログイン前)
        # このブロックは、上記で既にログイン前処理として実装済みのため、ここでは何もしない
        pass


# --- テストモード関連関数 ---
def start_new_test(df_vocab):
    test_settings = st.session_state.test_mode

    # 選択されたカテゴリでフィルタリング
    if test_settings['selected_category'] == '全カテゴリ':
        available_vocab = df_vocab.copy()
    else:
        available_vocab = df_vocab[df_vocab['カテゴリ (Category)'] == test_settings['selected_category']].copy()

    if available_vocab.empty or len(available_vocab) < test_settings['question_count']:
        st.error("選択された条件で十分な問題を作成できませんでした。カテゴリや問題数を見直してください。")
        st.session_state.test_mode['active'] = False
        return

    # 出題元に基づくフィルタリングと選択
    if test_settings['question_source'] == 'learning_focus':
        # 'Not Started' と 'Learning' の用語を優先
        focus_vocab = available_vocab[available_vocab['学習進捗 (Progress)'].isin(['Not Started', 'Learning'])]
        if len(focus_vocab) >= test_settings['question_count']:
            selected_questions_df = focus_vocab.sample(n=test_settings['question_count'], random_state=random.randint(0, 10000))
        elif len(focus_vocab) > 0: # 優先用語が足りなければ、残りをランダムに補完
            st.warning(f"学習不足用語が{len(focus_vocab)}件しかありませんでした。残りは他の用語からランダムに選択します。")
            remaining_count = test_settings['question_count'] - len(focus_vocab)
            other_vocab = available_vocab[~available_vocab.index.isin(focus_vocab.index)]
            selected_questions_df = pd.concat([
                focus_vocab,
                other_vocab.sample(n=remaining_count, random_state=random.randint(0, 10000))
            ])
        else: # 学習不足用語がない場合
            st.info("学習不足用語が見つからなかったため、全用語からランダムに選択します。")
            selected_questions_df = available_vocab.sample(n=test_settings['question_count'], random_state=random.randint(0, 10000))
    else: # 'random_all'
        selected_questions_df = available_vocab.sample(n=test_settings['question_count'], random_state=random.randint(0, 10000))

    questions = []
    for index, row in selected_questions_df.iterrows():
        correct_answer = ""
        question_text = ""
        if test_settings['test_type'] == 'term_to_def':
            question_text = f"用語: **{row['用語 (Term)']}** の説明として正しいものを選びなさい。"
            correct_answer = row['説明 (Definition)']
            options_pool = available_vocab['説明 (Definition)'].tolist()
        elif test_settings['test_type'] == 'example_to_term':
            if pd.isna(row['例文 (Example)']) or row['例文 (Example)'] == '':
                # 例文がない場合はスキップするか、他の形式にフォールバック
                continue 
            question_text = f"例文: 「*{row['例文 (Example)']}*」 が示す用語として正しいものを選びなさい。"
            correct_answer = row['用語 (Term)']
            options_pool = available_vocab['用語 (Term)'].tolist()
        
        # 選択肢を作成 (正解と異なるダミー選択肢を3つ追加)
        options = [correct_answer]
        dummy_options = [opt for opt in options_pool if opt != correct_answer]
        options.extend(random.sample(dummy_options, min(3, len(dummy_options))))
        random.shuffle(options)

        questions.append({
            'term_id': row['ID'],
            'term': row['用語 (Term)'],
            'definition': row['説明 (Definition)'],
            'example': row['例文 (Example)'],
            'category': row['カテゴリ (Category)'],
            'question_text': question_text,
            'correct_answer': correct_answer,
            'options': options
        })
    
    # 選択肢がない問題がスキップされた場合を考慮
    if not questions:
        st.error("選択された条件で有効な問題を作成できませんでした。例文が設定されていない用語が含まれている可能性があります。")
        st.session_state.test_mode['active'] = False
        return

    st.session_state.test_mode['active'] = True
    st.session_state.test_mode['current_question_index'] = 0
    st.session_state.test_mode['questions'] = questions
    st.session_state.test_mode['answers'] = [None] * len(questions)
    st.session_state.test_mode['score'] = 0
    st.session_state.test_mode['detailed_results'] = []
    st.rerun()


def run_test(df_vocab, current_test_results_table_name):
    test_mode = st.session_state.test_mode
    current_question = test_mode['questions'][test_mode['current_question_index']]

    st.subheader(f"問題 {test_mode['current_question_index'] + 1} / {len(test_mode['questions'])}")
    st.markdown(current_question['question_text'])

    user_answer = st.radio(
        "回答を選択してください:",
        current_question['options'],
        key=f"q_{test_mode['current_question_index']}"
    )
    
    st.session_state.test_mode['answers'][test_mode['current_question_index']] = user_answer

    col1, col2 = st.columns(2)
    with col1:
        if st.button("前の問題", key="prev_q"):
            if test_mode['current_question_index'] > 0:
                test_mode['current_question_index'] -= 1
                st.rerun()
    with col2:
        if st.button("次の問題", key="next_q"):
            if test_mode['current_question_index'] < len(test_mode['questions']) - 1:
                test_mode['current_question_index'] += 1
                st.rerun()
            else: # 最終問題の次を押したとき
                end_test(df_vocab, current_test_results_table_name)


def end_test(df_vocab, current_test_results_table_name):
    test_mode = st.session_state.test_mode
    total_score = 0
    detailed_results = []

    for i, question in enumerate(test_mode['questions']):
        user_answer = test_mode['answers'][i]
        is_correct = (user_answer == question['correct_answer'])
        
        if is_correct:
            total_score += 1
            # 学習進捗を更新（正解したらMasteredへ向かう）
            vocab_idx = df_vocab[df_vocab['ID'] == question['term_id']].index
            if not vocab_idx.empty:
                current_progress = df_vocab.loc[vocab_idx[0], '学習進捗 (Progress)']
                if current_progress == 'Not Started':
                    df_vocab.loc[vocab_idx[0], '学習進捗 (Progress)'] = 'Learning'
                elif current_progress == 'Learning':
                    df_vocab.loc[vocab_idx[0], '学習進捗 (Progress)'] = 'Mastered'
        else:
            # 不正解なら学習進捗をLearningに戻す
            vocab_idx = df_vocab[df_vocab['ID'] == question['term_id']].index
            if not vocab_idx.empty:
                df_vocab.loc[vocab_idx[0], '学習進捗 (Progress)'] = 'Learning'

        detailed_results.append({
            'term_id': question['term_id'],
            'term': question['term'],
            'definition': question['definition'],
            'question_text': question['question_text'],
            'correct_answer': question['correct_answer'],
            'user_answer': user_answer,
            'is_correct': is_correct
        })

    st.session_state.df_vocab = df_vocab # 更新されたdf_vocabをセッションステートに保存
    write_data_to_supabase(df_vocab, current_vocab_table_name) # 用語集データも更新

    # テスト結果を保存
    new_test_result = pd.DataFrame([{
        'Date': datetime.now(),
        'Category': test_mode['selected_category'],
        'TestType': test_mode['test_type'],
        'Score': total_score,
        'TotalQuestions': len(test_mode['questions']),
        'Details': detailed_results # ここがJSONBになる部分
    }])
    st.session_state.df_test_results = pd.concat([st.session_state.df_test_results, new_test_result], ignore_index=True)
    write_data_to_supabase(st.session_state.df_test_results, current_test_results_table_name)

    st.subheader("テスト終了！")
    st.success(f"あなたのスコア: {total_score} / {len(test_mode['questions'])}")
    
    if st.button("詳細結果を見る", key="view_detailed_results"):
        st.session_state.test_review_mode['active'] = True
        st.session_state.test_review_mode['review_index'] = 0
        st.session_state.test_review_mode['results_to_review'] = detailed_results
        st.session_state.test_mode['active'] = False # テストモードを終了
        go_to_page("テスト結果") # テスト結果ページに遷移

    if st.button("新しいテストを始める", key="start_new_test_after_finish"):
        st.session_state.test_mode['active'] = False
        st.rerun()

    if st.button("用語集に戻る", key="back_to_vocab_list_after_finish"):
        st.session_state.test_mode['active'] = False
        go_to_page("用語集")
