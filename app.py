import streamlit as st
import pandas as pd
import requests # requestsライブラリを追加
import json
import os

# --- 設定項目 ---
# GAS WebアプリのデプロイURL
GAS_WEBAPP_URL = "https://script.google.com/a/macros/tacoms-inc.com/s/AKfycbwNaOd61h9-NYG5xccl7qQrh20E20O3hPtZ7LSefMDGnZS7DJKFRi6aTERlNz7mD-z3PA/exec" # ★★★
# GASで設定したAPIキー
GAS_API_KEY = "my_streamlit_secret_key_123" # ★★★ GASで設定したALLOWED_API_KEYと同じ値を貼り付ける ★★★

# --- Streamlit アプリケーションの開始 ---
st.set_page_config(layout="wide")
st.title("ビジネス用語集ビルダー")

# ユーザー認証の状態を管理するセッションステート
if 'username' not in st.session_state:
    st.session_state.username = None

# --- GAS APIとの連携関数 ---
@st.cache_data(ttl=60) # 1分キャッシュ
def load_data_from_gas(sheet_name):
    """GAS Webアプリからデータを読み込む"""
    try:
        params = {'api_key': GAS_API_KEY, 'sheet': sheet_name}
        response = requests.get(GAS_WEBAPP_URL, params=params)
        response.raise_for_status() # HTTPエラーが発生した場合に例外を投げる
        data = response.json()

        if 'error' in data:
            st.error(f"GASからエラーが返されました: {data['error']}")
            st.stop()
        
        df = pd.DataFrame(data['data'])
        
        # ヘッダーが一部欠けている場合や、ID列がない場合の対策
        expected_cols = ['ID', '用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)', '学習進捗 (Progress)']
        for col in expected_cols:
            if col not in df.columns:
                df[col] = '' # 存在しない列は空で追加

        df = df[expected_cols] # 列の順番を保証
        df = df.dropna(how='all') # 全てがNaNの行を削除

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
    """GAS Webアプリ経由でデータを書き込む"""
    try:
        # DataFrameをGASが期待する形式（ヘッダーを含むリストのリスト）に変換
        data_to_send = [df.columns.tolist()] + df.values.tolist()

        params = {'api_key': GAS_API_KEY, 'sheet': sheet_name}
        headers = {'Content-Type': 'application/json'}
        response = requests.post(GAS_WEBAPP_URL, params=params, headers=headers, json={'data': data_to_send})
        response.raise_for_status() # HTTPエラーが発生した場合に例外を投げる
        result = response.json()

        if 'error' in result:
            st.error(f"GAS書き込み中にエラーが返されました: {result['error']}")
            return False
        
        st.success(f"データがスプレッドシート '{sheet_name}' に保存されました！")
        st.cache_data.clear() # キャッシュをクリアして最新データを再読み込み
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
            st.rerun() # ユーザー名設定後にアプリを再実行

# --- ユーザーログイン後のメインコンテンツ ---
if st.session_state.username:
    st.sidebar.write(f"ようこそ、**{st.session_state.username}** さん！")
    
    # ユーザー名に基づいてシート名を決定
    sanitized_username = "".join(filter(str.isalnum, st.session_state.username))
    current_worksheet_name = f"Sheet_{sanitized_username}"

    # --- メイン処理 ---
    df_vocab = load_data_from_gas(current_worksheet_name) # GASから読み込む関数に変更

    # サイドバー
    st.sidebar.header("ナビゲーション")
    page = st.sidebar.radio("Go to", ["用語一覧", "用語の追加・編集", "データ管理"])

    if page == "用語一覧":
        st.header("登録済みビジネス用語")

        if not df_vocab.empty:
            # カテゴリフィルタ
            all_categories = ['全てのカテゴリ'] + sorted(df_vocab['カテゴリ (Category)'].dropna().unique().tolist())
            selected_category = st.selectbox("カテゴリで絞り込む:", all_categories)

            filtered_df = df_vocab.copy()
            if selected_category != '全てのカテゴリ':
                filtered_df = filtered_df[filtered_df['カテゴリ (Category)'] == selected_category]
            
            # 検索ボックス
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
            
            # 既存カテゴリの候補
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
                    if write_data_to_gas(updated_df, current_worksheet_name): # GASに書き込む関数に変更
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
                            if write_data_to_gas(df_vocab, current_worksheet_name): # GASに書き込む関数に変更
                                st.success(f"用語 '{edited_term}' が更新されました！")
                                st.rerun()
                        else:
                            st.error("用語、説明、カテゴリは必須項目です。")
                    
                    if delete_submitted:
                        df_vocab = df_vocab[df_vocab['ID'] != selected_term_data['ID']]
                        if write_data_to_gas(df_vocab, current_worksheet_name): # GASに書き込む関数に変更
                            st.warning(f"用語 '{selected_term_data['用語 (Term)']}' が削除されました。")
                            st.rerun()
        else:
            st.info("編集・削除できる用語がありません。")

    elif page == "データ管理":
        st.header("データ管理")
        st.subheader("学習進捗のリセット")
        st.warning(f"**{st.session_state.username}** さんの学習進捗を全てリセットします。この操作は元に戻せません。")
        
        if st.button("学習進捗をリセットする"):
            if not df_vocab.empty:
                df_vocab['学習進捗 (Progress)'] = 'Not Started'
                if write_data_to_gas(df_vocab, current_worksheet_name): # GASに書き込む関数に変更
                    st.success("学習進捗がリセットされました！")
                    st.rerun() # リセット後、表示を更新
            else:
                st.info("リセットする学習データがありません。")

else:
    st.empty() # ユーザー名入力中は他のコンテンツを表示しない