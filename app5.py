import streamlit as st
import pandas as pd
import requests
import json
import os
import random # ★★★ ここに import random を追加しました ★★★

# --- 設定項目 ---
# GAS WebアプリのデプロイURL
GAS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbwro4Xl-tIdlgg5nPhppfGJMYvzdVFUEi5Qf8REWo0eoyL5aCJmtKHOZNjQH7No7llZWQ/exec" # ★★★
# GASで設定したAPIキー
GAS_API_KEY = "my_streamlit_secret_key_123" # ★★★ GASで設定したALLOWED_API_KEYと同じ値を貼り付ける ★★★

# --- Streamlit アプリケーションの開始 ---
st.set_page_config(layout="wide")
st.title("ビジネス用語集ビルダー")

if 'username' not in st.session_state:
    st.session_state.username = None

# --- GAS APIとの連携関数 (変更なし) ---
@st.cache_data(ttl=60)
def load_data_from_gas(sheet_name):
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

# --- ユーザー名入力処理 (変更なし) ---
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
            'type': None,
            'current_question': None,
            'current_answer': None,
            'choices': [],
            'score': 0,
            'total_questions': 0,
            'answered': False,
            'selected_category_filter': '全てのカテゴリ'
        }
    
    # セッションステートの初期化（学習ビュー用）
    if 'learning_view' not in st.session_state:
        st.session_state.learning_view = {
            'filtered_df_indices': [],
            'current_index_in_filtered': 0,
            'selected_category': '全てのカテゴリ',
            'progress_filter': '全ての進捗'
        }

    # --- テスト問題生成ヘルパー関数 (修正なし) ---
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
                # ただし、無限ループにならないよう、ある程度試行回数を制限するか、
                # 例文のない用語を除外するロジックが必要。
                # 現状は、例文なしの用語が対象になった場合、再度同じロジックで試行する
                # (結果的に例文のある用語が選ばれるか、再度例文なしが選ばれる)
                eligible_for_example = vocab_df[pd.notna(vocab_df['例文 (Example)']) & (vocab_df['例文 (Example)'] != '')]
                if eligible_for_example.empty:
                    return None # 例文のある用語がない
                question_term_row = eligible_for_example.sample(n=1).iloc[0] # 例文があるものから再選択
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

    # --- テストモードの開始・リセット (修正なし) ---
    def start_new_test(test_type, category_filter_for_test):
        st.session_state.test_mode['type'] = test_type
        st.session_state.test_mode['score'] = 0
        st.session_state.test_mode['total_questions'] = 0
        st.session_state.test_mode['answered'] = False
        st.session_state.test_mode['current_question'] = None
        st.session_state.test_mode['selected_category_filter'] = category_filter_for_test
        st.session_state.current_answer_selection = None
        generate_next_question()

    # --- テストモードの次の問題生成 (修正なし) ---
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
        idx = df_vocab[df_vocab['ID'] == term_id].index[0]
        if current_progress_value == 'Not Started':
            df_vocab.loc[idx, '学習進捗 (Progress)'] = 'Learning'
            st.toast(f"用語の学習を開始しました！")
        elif current_progress_value == 'Learning':
            df_vocab.loc[idx, '学習進捗 (Progress)'] = 'Mastered'
            st.toast(f"用語を習得済みにしました！")
        
        # 変更があった場合のみ書き込み
        if df_vocab.loc[idx, '学習進捗 (Progress)'] != current_progress_value:
            write_data_to_gas(df_vocab, current_worksheet_name) # 更新をスプレッドシートに反映

    # --- ナビゲーション ---
    st.sidebar.header("ナビゲーション")
    # ★★★ ナビゲーションメニューの並び替え ★★★
    page = st.sidebar.radio("Go to", [
        "学習ビュー",
        "テストモード",
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

    elif page == "学習ビュー":
        st.header("学習ビュー")

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
                                                    index=all_categories.index(st.session_state.learning_view['selected_category']))
        with col_filter2:
            selected_progress_filter = st.selectbox("学習進捗で絞り込む:", progress_options,
                                                    key="learn_progress_filter",
                                                    index=progress_options.index(st.session_state.learning_view['progress_filter']))
        
        # フィルタリングロジック
        filtered_df = df_vocab.copy()
        if selected_category_filter != '全てのカテゴリ':
            filtered_df = filtered_df[filtered_df['カテゴリ (Category)'] == selected_category_filter]
        if selected_progress_filter != '全ての進捗':
            filtered_df = filtered_df[filtered_df['学習進捗 (Progress)'] == selected_progress_filter]
        
        # フィルタリング条件が変わったかチェック
        if (selected_category_filter != st.session_state.learning_view['selected_category'] or
            selected_progress_filter != st.session_state.learning_view['progress_filter']):
            st.session_state.learning_view['selected_category'] = selected_category_filter
            st.session_state.learning_view['progress_filter'] = selected_progress_filter
            st.session_state.learning_view['filtered_df_indices'] = filtered_df.index.tolist()
            st.session_state.learning_view['current_index_in_filtered'] = 0
            if not filtered_df.empty:
                st.rerun()

        if filtered_df.empty:
            st.info("この条件に一致する用語は見つかりませんでした。")
            st.stop()
        
        # 現在表示する用語のインデックスを取得
        total_terms_in_filtered = len(filtered_df)
        current_display_index_in_filtered = st.session_state.learning_view['current_index_in_filtered']

        original_idx = st.session_state.learning_view['filtered_df_indices'][current_display_index_in_filtered]
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
                # ★★★ 進捗自動更新ロジック ★★★
                update_progress_for_navigation(current_term_data['ID'], current_term_data['学習進捗 (Progress)'])
                st.session_state.learning_view['current_index_in_filtered'] -= 1
                st.rerun()
        with col_random:
            if st.button("ランダムな用語へ"):
                # ★★★ 進捗自動更新ロジック ★★★
                update_progress_for_navigation(current_term_data['ID'], current_term_data['学習進捗 (Progress)'])
                st.session_state.learning_view['current_index_in_filtered'] = random.randrange(total_terms_in_filtered)
                st.rerun()
        with col_next:
            if st.button("次の用語へ", disabled=(current_display_index_in_filtered >= total_terms_in_filtered - 1)):
                # ★★★ 進捗自動更新ロジック ★★★
                update_progress_for_navigation(current_term_data['ID'], current_term_data['学習進捗 (Progress)'])
                st.session_state.learning_view['current_index_in_filtered'] += 1
                st.rerun()

    elif page == "テストモード":
        st.header("テストモード")

        # カテゴリフィルタのUI
        all_categories_for_test = ['全てのカテゴリ'] + sorted(df_vocab['カテゴリ (Category)'].dropna().unique().tolist())
        selected_category_filter_for_test = st.selectbox("カテゴリで絞り込む:", all_categories_for_test,
                                                        key="test_category_filter",
                                                        index=all_categories_for_test.index(st.session_state.test_mode['selected_category_filter']))

        # 絞り込み後の用語数を確認
        filtered_df_for_test = df_vocab.copy()
        if selected_category_filter_for_test != '全てのカテゴリ':
            filtered_df_for_test = filtered_df_for_test[filtered_df_for_test['カテゴリ (Category)'] == selected_category_filter_for_test]

        if filtered_df_for_test.empty or len(filtered_df_for_test) < 4:
            st.warning("このカテゴリには、テストを開始するための十分な用語（4つ以上）がありません。別のカテゴリを選択するか、用語を追加してください。")
            st.stop()
        
        test_type_selection = st.radio("テスト形式を選択してください:", 
                                       ["用語から説明を選択", "例文から用語を選択"],
                                       key="test_type_selector")

        selected_test_type = ''
        if test_type_selection == "用語から説明を選択":
            selected_test_type = 'term_to_def'
        else:
            selected_test_type = 'example_to_term'

        # テストの開始条件を見直し
        if (st.session_state.test_mode['type'] != selected_test_type or
            st.session_state.test_mode['selected_category_filter'] != selected_category_filter_for_test or
            st.sidebar.button("テストをやり直す", key="reset_test_button")):
            
            start_new_test(selected_test_type, selected_category_filter_for_test)
            st.rerun()

        # 現在の問題を生成または表示
        if st.session_state.test_mode['current_question'] is None:
            # generate_next_questionは既にフィルタを考慮している
            generate_next_question() 
            st.rerun()

        current_q = st.session_state.test_mode['current_question']
        if current_q is None:
            st.error("問題の生成に失敗しました。選択したカテゴリに適切なデータが登録されているか確認してください。")
            st.stop()
        
        st.subheader(f"問題 {st.session_state.test_mode['total_questions'] + 1}")
        
        if st.session_state.test_mode['type'] == 'term_to_def':
            st.write(f"### 用語: **{current_q['question_text']}**")
            st.write("正しい説明を選択してください。")
        elif st.session_state.test_mode['type'] == 'example_to_term':
            st.write(f"### 例文: **{current_q['question_text']}**")
            st.write("正しい用語を選択してください。")
        
        st.session_state.current_answer_selection = st.radio("選択肢:", current_q['choices'], 
                                                            index=None,
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
                    st.toast("学習進捗を更新しました！")
                    idx = df_vocab[df_vocab['ID'] == current_q['question_id']].index[0]
                    df_vocab.loc[idx, '学習進捗 (Progress)'] = 'Learning' # 不正解の場合はLearningに戻す
                    write_data_to_gas(df_vocab, current_worksheet_name)
                st.rerun()
        
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