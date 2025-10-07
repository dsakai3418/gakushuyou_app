import streamlit as st
import pandas as pd
import requests
import json
import os
import random

# --- 設定項目 ---
GAS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbyC-Bp4NI28c6kKTRcecj9SwI1TXWoAXUoz4NJ2OTLiHTI8RHW8D00isT_Hzri71Tj9sg/exec"
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
        response.raise_for_status()
        data = response.json()

        if 'error' in data:
            st.error(f"GASからエラーが返されました: {data['error']}")
            # 特定のエラー（シートが存在しないなど）の場合はdfを空で返す
            if "シートが見つかりません" in data['error'] or "Sheet not found" in data['error']:
                return pd.DataFrame(columns=['ID', '用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)', '学習進捗 (Progress)'])
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
    try:
        data_to_send = [df.columns.tolist()] + df.values.tolist()
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
        st.error("GASからのレスポンスをJSONとして解析できませんでした。GASのコードを確認してください。")
        return False
    except Exception as e:
        st.error(f"データの書き込み中に予期せぬエラーが発生しました: {e}")
        return False

# ★★★ マスターシートからコピーする関数を追加 ★★★
def copy_master_sheet_to_user_sheet(user_sheet_name):
    try:
        params = {
            'api_key': GAS_API_KEY, 
            'action': 'copy_sheet',
            'source_sheet': 'Master',
            'target_sheet': user_sheet_name
        }
        response = requests.post(GAS_WEBAPP_URL, params=params)
        response.raise_for_status()
        result = response.json()

        if 'error' in result:
            st.error(f"マスターシートのコピー中にGASからエラー: {result['error']}")
            return False
        
        st.success(f"マスターシートから '{user_sheet_name}' を作成しました！")
        st.cache_data.clear() # キャッシュをクリアして新しいシートを読み込む
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"GAS Webアプリへのコピーリクエスト失敗: {e}")
        return False
    except json.JSONDecodeError:
        st.error("GASからのコピーレスポンスをJSONとして解析できませんでした。GASのコードを確認してください。")
        return False
    except Exception as e:
        st.error(f"マスターシートのコピー中に予期せぬエラーが発生: {e}")
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

    # ★★★ ユーザーシートの存在チェックとMasterからのコピー ★★★
    # ユーザーシートが空DataFrameとして返ってきた場合、シートが存在しないと判断
    df_vocab_check = load_data_from_gas(current_worksheet_name)
    if df_vocab_check.empty and 'sheet_initialized' not in st.session_state:
        st.info(f"あなたの用語集 '{current_worksheet_name}' が見つかりませんでした。マスター用語集からコピーを作成します。")
        if copy_master_sheet_to_user_sheet(current_worksheet_name):
            st.session_state.sheet_initialized = True
            st.rerun() # 新しいシートができたので再読み込み
        else:
            st.error("用語集の初期化に失敗しました。GASの設定を確認してください。")
            st.stop()
    
    df_vocab = load_data_from_gas(current_worksheet_name) # 最新のデータを再読み込み

    # セッションステートの初期化（テストモード用）
    if 'test_mode' not in st.session_state:
        st.session_state.test_mode = {
            'type': None,
            'current_question': None,
            'current_answer': None,
            'choices': [],
            'score': 0,
            'total_questions': 0,
            'answered': False,
            'selected_category_filter': '全てのカテゴリ'
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
    def generate_question(test_type, vocab_df, category_filter='全てのカテゴリ'):
        # カテゴリで絞り込み
        if category_filter != '全てのカテゴリ':
            vocab_df = vocab_df[vocab_df['カテゴリ (Category)'] == category_filter]

        if vocab_df.empty or len(vocab_df) < 1:
            return None # 問題を生成できない
        
        # 出題対象の用語をランダムに選択
        question_term_row = vocab_df.sample(n=1).iloc[0]
        
        correct_answer = ""
        question_text = ""
        all_options_pool = []

        if test_type == 'term_to_def':
            question_text = question_term_row['用語 (Term)']
            correct_answer = question_term_row['説明 (Definition)']
            all_options_pool = vocab_df['説明 (Definition)'].tolist()
        elif test_type == 'example_to_term':
            if pd.isna(question_term_row['例文 (Example)']) or question_term_row['例文 (Example)'] == '':
                # 例文がない場合は、同じカテゴリ内で別の用語を探す
                eligible_for_example = vocab_df[pd.notna(vocab_df['例文 (Example)']) & (vocab_df['例文 (Example)'] != '')]
                if eligible_for_example.empty:
                    return None # 例文のある用語がない
                question_term_row = eligible_for_example.sample(n=1).iloc[0]
            question_text = question_term_row['例文 (Example)']
            correct_answer = question_term_row['用語 (Term)']
            all_options_pool = vocab_df['用語 (Term)'].tolist()
        
        # 不正解の選択肢を選ぶ（最大3つ）
        incorrect_choices = []
        possible_incorrects = [opt for opt in all_options_pool if opt != correct_answer]
        if len(possible_incorrects) > 3:
            incorrect_choices = random.sample(possible_incorrects, 3)
        else:
            incorrect_choices = possible_incorrects

        choices = [correct_answer] + incorrect_choices
        random.shuffle(choices)

        return {
            'question_text': question_text,
            'correct_answer': correct_answer,
            'choices': choices,
            'question_id': question_term_row['ID']
        }

    # --- テストモードの開始・リセット ---
    def start_new_test(test_type, category_filter_for_test):
        st.session_state.test_mode['type'] = test_type
        st.session_state.test_mode['score'] = 0
        st.session_state.test_mode['total_questions'] = 0
        st.session_state.test_mode['answered'] = False
        st.session_state.test_mode['current_question'] = None
        st.session_state.test_mode['selected_category_filter'] = category_filter_for_test
        st.session_state.current_answer_selection = None
        generate_next_question()

    # --- テストモードの次の問題生成 ---
    def generate_next_question():
        st.session_state.test_mode['current_question'] = generate_question(
            st.session_state.test_mode['type'], 
            df_vocab, 
            st.session_state.test_mode['selected_category_filter']
        )
        st.session_state.test_mode['current_answer'] = None
        st.session_state.test_mode['choices'] = st.session_state.test_mode['current_question']['choices'] if st.session_state.test_mode['current_question'] else []
        st.session_state.test_mode['answered'] = False
        st.session_state.current_answer_selection = None

    # --- 学習進捗を自動更新するヘルパー関数 ---
    def update_progress_for_navigation(term_id, current_progress_value):
        global df_vocab # df_vocabをグローバルとして扱う
        idx_list = df_vocab[df_vocab['ID'] == term_id].index.tolist()
        if not idx_list:
            return # IDが見つからない場合は何もしない

        idx = idx_list[0] # 最初に見つかったインデックスを使用

        if current_progress_value == 'Not Started':
            df_vocab.loc[idx, '学習進捗 (Progress)'] = 'Learning'
            st.toast(f"用語の学習を開始しました！")
            write_data_to_gas(df_vocab, current_worksheet_name)
        elif current_progress_value == 'Learning':
            df_vocab.loc[idx, '学習進捗 (Progress)'] = 'Mastered'
            st.toast(f"用語を習得済みにしました！")
            write_data_to_gas(df_vocab, current_worksheet_name)
        
        # 明示的な更新は上記で処理済み
        # 変更があった場合のみ書き込み (今回は上記で毎回書き込むように変更)


    # --- ナビゲーション ---
    st.sidebar.header("ナビゲーション")
    # ★★★ ナビゲーションメニューの並び替えと「学習モード」表記変更 ★★★
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
        
        # フィルタリングオプション
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
        
        # フィルタリングロジック
        filtered_df = df_vocab.copy()
        if selected_category_filter != '全てのカテゴリ':
            filtered_df = filtered_df[filtered_df['カテゴリ (Category)'] == selected_category_filter]
        if selected_progress_filter != '全ての進捗':
            filtered_df = filtered_df[filtered_df['学習進捗 (Progress)'] == selected_progress_filter]
        
        # フィルタリング条件が変わったかチェック
        if (selected_category_filter != st.session_state.learning_mode['selected_category'] or
            selected_progress_filter != st.session_state.learning_mode['progress_filter']):
            st.session_state.learning_mode['selected_category'] = selected_category_filter
            st.session_state.learning_mode['progress_filter'] = selected_progress_filter
            st.session_state.learning_mode['filtered_df_indices'] = filtered_df.index.tolist()
            st.session_state.learning_mode['current_index_in_filtered'] = 0
            if not filtered_df.empty:
                st.rerun()

        # ここでエラーチェックを追加
        if filtered_df.empty:
            st.info("この条件に一致する用語は見つかりませんでした。")
            # セッションステートのリセット
            st.session_state.learning_mode['filtered_df_indices'] = []
            st.session_state.learning_mode['current_index_in_filtered'] = 0
            st.stop()
        
        # 現在表示する用語のインデックスを取得
        total_terms_in_filtered = len(filtered_df)
        current_display_index_in_filtered = st.session_state.learning_mode['current_index_in_filtered']

        # 現在のインデックスが範囲外にならないように調整
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
        new_progress = st.selectbox("学習進捗を更新する:", 
                                    options=['Not Started', 'Learning', 'Mastered'],
                                    index=['Not Started', 'Learning', 'Mastered'].index(current_term_data['学習進捗 (Progress)']),
                                    key=f"progress_update_{current_term_data['ID']}")
        
        # 明示的に学習進捗が変更された場合
        if new_progress != current_term_data['学習進捗 (Progress)']:
            df_vocab.loc[original_idx, '学習進捗 (Progress)'] = new_progress
            if write_data_to_gas(df_vocab, current_worksheet_name):
                st.success(f"'{current_term_data['用語 (Term)']}' の学習進捗が '{new_progress}' に更新されました！")
                st.rerun()

        st.markdown("---")

        col_prev, col_random, col_next = st.columns(3)
        with col_prev:
            if st.button("前の用語へ", disabled=(current_display_index_in_filtered == 0)):
                update_progress_for_navigation(current_term_data['ID'], current_term_data['学習進捗 (Progress)'])
                st.session_state.learning_mode['current_index_in_filtered'] -= 1
                st.rerun()
        with col_random:
            if st.button("ランダムな用語へ"):
                update_progress_for_navigation(current_term_data['ID'], current_term_data['学習進捗 (Progress)'])
                st.session_state.learning_mode['current_index_in_filtered'] = random.randrange(total_terms_in_filtered)
                st.rerun()
        with col_next:
            if st.button("次の用語へ", disabled=(current_display_index_in_filtered >= total_terms_in_filtered - 1)):
                update_progress_for_navigation(current_term_data['ID'], current_term_data['学習進捗 (Progress)'])
                st.session_state.learning_mode['current_index_in_filtered'] += 1
                st.rerun()

    elif page == "辞書モード":
        st.header("辞書モード")

        if df_vocab.empty:
            st.info("辞書に登録された用語がありません。「用語の追加・編集」から追加してください。")
            st.stop()
        
        all_categories = ['全てのカテゴリ'] + sorted(df_vocab['カテゴリ (Category)'].dropna().unique().tolist())

        # 検索バーとカテゴリフィルタ
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
        
        # カテゴリフィルタ適用
        if st.session_state.dictionary_mode['selected_category'] != '全てのカテゴリ':
            filtered_df = filtered_df[filtered_df['カテゴリ (Category)'] == st.session_state.dictionary_mode['selected_category']]
        
        # 検索フィルタ適用
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
            # 検索結果をアコーディオンで表示
            for _, row in filtered_df.iterrows():
                # expandedの状態をセッションステートで管理
                is_expanded = (st.session_state.dictionary_mode['expanded_term_id'] == row['ID'])
                with st.expander(f"**{row['用語 (Term)']}.** （カテゴリ: {row['カテゴリ (Category)']}）", 
                                  expanded=is_expanded):
                    st.write(f"### 説明")
                    st.markdown(f"**{row['説明 (Definition)']}**")
                    if pd.notna(row['例文 (Example)']) and row['例文 (Example)'] != '': # ★★★ ここが途切れていた部分 ★★★
                        st.write(f"### 例文")
                        st.markdown(f"*{row['例文 (Example)']}*")
                    
                    # 展開・非展開の切り替えロジック
                    if is_expanded:
                        if st.button("閉じる", key=f"close_{row['ID']}"):
                            st.session_state.dictionary_mode['expanded_term_id'] = None
                            st.rerun()
                    else:
                        if st.button("詳細を見る", key=f"open_{row['ID']}"):
                            st.session_state.dictionary_mode['expanded_term_id'] = row['ID']
                            st.rerun()
                st.markdown("---") # 各用語の区切り線

    elif page == "テストモード":
        st.header("テストモード")
        if df_vocab.empty:
            st.info("テストする用語がありません。「用語の追加・編集」から追加してください。")
            st.stop()

        all_categories_for_test = ['全てのカテゴリ'] + sorted(df_vocab['カテゴリ (Category)'].dropna().unique().tolist())
        selected_category_for_test = st.selectbox("テストするカテゴリを選択:", all_categories_for_test,
                                                key="test_category_filter",
                                                index=all_categories_for_test.index(st.session_state.test_mode['selected_category_filter']))

        if st.session_state.test_mode['type'] is None:
            st.subheader("テスト形式を選択してください")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("用語 → 説明テスト", key="start_term_def_test"):
                    start_new_test('term_to_def', selected_category_for_test)
            with col2:
                if st.button("例文 → 用語テスト", key="start_example_term_test"):
                    start_new_test('example_to_term', selected_category_for_test)
            st.info("※例文のない用語は出題されません（例文 → 用語テストの場合）。")
        else:
            # テスト問題の生成に失敗した場合のハンドリング
            if st.session_state.test_mode['current_question'] is None:
                st.warning("このカテゴリではテスト問題が作成できませんでした。用語数や例文の有無を確認してください。")
                if st.button("テストを終了する", key="end_test_no_q"):
                    st.session_state.test_mode['type'] = None
                    st.rerun()
                st.stop()


            st.subheader(f"現在のスコア: {st.session_state.test_mode['score']} / {st.session_state.test_mode['total_questions']}")
            st.write(f"**問題:** {st.session_state.test_mode['current_question']['question_text']}")

            # 回答の選択肢を表示
            with st.form(key=f"question_form_{st.session_state.test_mode['total_questions']}"):
                selected_choice = st.radio("選択肢:", st.session_state.test_mode['choices'], 
                                           key=f"radio_{st.session_state.test_mode['total_questions']}",
                                           disabled=st.session_state.test_mode['answered'])
                submit_answer = st.form_submit_button("回答を送信", disabled=st.session_state.test_mode['answered'])

                if submit_answer:
                    st.session_state.test_mode['answered'] = True
                    st.session_state.test_mode['total_questions'] += 1
                    
                    correct_answer = st.session_state.test_mode['current_question']['correct_answer']
                    if selected_choice == correct_answer:
                        st.session_state.test_mode['score'] += 1
                        st.success("正解！🎉")
                        # 正解した用語の進捗を更新
                        current_progress = df_vocab[df_vocab['ID'] == st.session_state.test_mode['current_question']['question_id']]['学習進捗 (Progress)'].iloc[0]
                        if current_progress == 'Learning':
                            update_progress_for_navigation(st.session_state.test_mode['current_question']['question_id'], current_progress)
                        elif current_progress == 'Not Started': # Not Startedの場合はLearningに
                            df_vocab.loc[df_vocab['ID'] == st.session_state.test_mode['current_question']['question_id'], '学習進捗 (Progress)'] = 'Learning'
                            write_data_to_gas(df_vocab, current_worksheet_name)
                    else:
                        st.error(f"不正解... 😔 正解は **{correct_answer}** でした。")
                    
                    # 回答後に次の問題ボタンを表示
                    st.button("次の問題へ", on_click=generate_next_question, key="next_question_button")
            
            # テスト終了ボタン
            if st.button("テストを終了する", key="end_test_session"):
                st.session_state.test_mode['type'] = None
                st.rerun()

    elif page == "データ管理":
        st.header("データ管理")
        st.info(f"あなたのデータはGoogleスプレッドシートの '{current_worksheet_name}' シートに保存されています。")

        st.subheader("全用語データのエクスポート")
        if not df_vocab.empty:
            csv = df_vocab.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="CSVでダウンロード",
                data=csv,
                file_name=f"{sanitized_username}_business_terms.csv",
                mime="text/csv",
            )
            st.info("現在のすべての用語データをCSVファイルとしてダウンロードできます。")
        else:
            st.info("エクスポートできる用語がありません。")

        st.subheader("用語データの一括インポート (CSV)")
        st.warning("既存のデータは上書きされる可能性があります。事前にデータをダウンロードすることを強く推奨します。")
        uploaded_file = st.file_uploader("CSVファイルをアップロードしてください", type=["csv"])
        if uploaded_file is not None:
            try:
                imported_df = pd.read_csv(uploaded_file)
                # 必須カラムのチェック
                required_cols = ['用語 (Term)', '説明 (Definition)', 'カテゴリ (Category)']
                if not all(col in imported_df.columns for col in required_cols):
                    st.error(f"CSVファイルには以下の必須カラムが含まれている必要があります: {', '.join(required_cols)}")
                else:
                    # IDの再生成と欠落カラムの補完
                    imported_df['ID'] = range(1, len(imported_df) + 1)
                    for col in ['例文 (Example)', '学習進捗 (Progress)']:
                        if col not in imported_df.columns:
                            imported_df[col] = ''
                    imported_df['学習進捗 (Progress)'] = imported_df['学習進捗 (Progress)'].fillna('Not Started') # デフォルト値

                    if st.button("インポートを実行 (既存データ上書きの可能性あり)"):
                        if write_data_to_gas(imported_df, current_worksheet_name):
                            st.success("CSVデータが正常にインポートされました！")
                            st.rerun()
            except Exception as e:
                st.error(f"CSVファイルの読み込みまたは処理中にエラーが発生しました: {e}")