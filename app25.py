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

# st.session_state の初期化は、usernameチェックより前に行う
if 'username' not in st.session_state:
    st.session_state.username = None
if 'current_page' not in st.session_state:
    st.session_state.current_page = "Welcome" # 初期ページをWelcomeに設定

# --- GAS APIとの連携関数 ---
# カスタムJSONエンコーダー (GASに直接送信するJSONシリアライズ処理では不要になる可能性が高いが、残しておく)
def json_serial_for_gas(obj):
    """datetime, date, Pandas TimestampオブジェクトをISOフォーマット文字列に変換するカスタムJSONシリアライザー"""
    if isinstance(obj, (datetime, pd.Timestamp, date)):
        return obj.isoformat()
    if isinstance(obj, pd.Int64Dtype.type):
        return int(obj)
    if isinstance(obj, bool): # Python bool
        return bool(obj)
    # PandasのBooleanDtypeの型を直接チェック
    if isinstance(obj, (pd.api.types.BooleanDtype().type)):
        return bool(obj)
    # SeriesやDataFrameが意図せず含まれた場合
    if isinstance(obj, pd.Series):
        return obj.to_dict()
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient='records')
    # numpyの真偽値型
    if hasattr(obj, 'dtype') and str(obj.dtype).startswith('bool'):
        return bool(obj)
    # NumPyの整数型
    if hasattr(obj, 'dtype') and str(obj.dtype).startswith('int'):
        return int(obj)
    # NumPyの浮動小数点数型
    if hasattr(obj, 'dtype') and str(obj.dtype).startswith('float'):
        return float(obj)

    # ★★★ ここが重要: dictやlistが直接含まれる場合、json.dumps()で処理するように変更 ★★★
    if isinstance(obj, dict) or isinstance(obj, list):
        return json.dumps(obj, ensure_ascii=False, default=json_serial_for_gas)

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
            
            # ★★★ ここがエラーの原因箇所なので、parse_json_safelyを強化 ★★★
            if 'Details' in df.columns and not df.empty:
                def parse_json_safely(json_str):
                    if pd.isna(json_str) or not isinstance(json_str, str) or not json_str.strip():
                        return []
                    try:
                        return json.loads(json_str)
                    except (json.JSONDecodeError, TypeError):
                        # エラーログを改善
                        st.warning(f"テスト結果の詳細データをJSONとしてパースできませんでした: {str(json_str)[:200]}...") # エラー箇所の表示を増やす
                        # 不正な形式の場合、今回は空リストを返すことで処理を続行
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
        st.exception(e) # デバッグ用
        return pd.DataFrame(columns=TEST_RESULTS_HEADERS if sheet_name.startswith("Sheet_TestResults_") else VOCAB_HEADERS)

# === write_data_to_gas 関数を全面的に刷新 ===
def write_data_to_gas(df, sheet_name, action='write_data'):
    try:
        # ★★★ ここから修正 ★★★
        # 'Details'カラムを事前にJSON文字列に変換
        if sheet_name.startswith("Sheet_TestResults_") and 'Details' in df.columns:
            # 各要素がリストや辞書の場合にjson.dumps()を適用
            # pd.isna()でNaNチェックも行う
            df_to_send = df.copy() # 送信用にコピー
            df_to_send['Details'] = df_to_send['Details'].apply(
                lambda x: json.dumps(x, ensure_ascii=False, default=json_serial_for_gas) if not pd.isna(x) else ''
            )
        else:
            df_to_send = df.copy()
        
        # DataFrameをJSON文字列に変換 (df_to_sendを使用)
        # default=json_serial_for_gas は残しておくが、Detailsは既に処理済み
        df_json_str = df_to_send.to_json(orient='split', date_format='iso', default=json_serial_for_gas, force_ascii=False)
        # ★★★ ここまで修正 ★★★
        
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
        
        st.cache_data.clear()
        st.sidebar.write(f"DEBUG: Data successfully written to GAS for sheet '{sheet_name}'.")
        return True
    except requests.exceptions.RequestException as e:
        st.error(f"GAS Webアプリへの書き込み接続に失敗しました: {e}")
        st.info(f"GAS WebアプリのURL: {GAS_WEBAPP_URL} が正しいか、デプロイされているか確認してください。")
        st.exception(e) # デバッグ用
        return False
    except json.JSONDecodeError as e:
        st.error(f"GASからのレスポンスをJSONとして解析できませんでした。エラー: {e}。レスポンス内容: {response.text}。GASのコードを確認してください。")
        st.exception(e) # デバッグ用
        return False
    except Exception as e:
        st.error(f"データの書き込み中に予期せぬエラーが発生しました: {e}")
        st.exception(e) # デバッグ用
        return False

# ... (以降のStreamlitアプリのロジックは変更なし) ...

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

    # df_test_resultsがまだ空の場合はヘッダーを先に作成
    if df_test_results.empty:
        df_test_results = pd.DataFrame(columns=TEST_RESULTS_HEADERS)

    # 新しい結果を行として追加
    new_result_row_data = {
        'Date': test_date_obj,
        'Category': category_used,
        'TestType': test_type_display,
        'Score': final_score,
        'TotalQuestions': len(questions),
        'Details': current_detailed_results # ★★★ ここはjson.dumpsせず生のリストオブジェクトのまま ★★★
    }
    # pandas.concatの代わりに_appendを使用 (将来のバージョンでのwarning回避のため)
    df_test_results = df_test_results._append(new_result_row_data, ignore_index=True)

    # write_data_to_gasにDataFrame全体を渡す
    # write_data_to_gas内でDetailsカラムのjson.dumpsが適用される
    write_success_results = write_data_to_gas(df_test_results, test_results_sheet_name)

    if write_success_results:
        st.success("テスト結果が保存されました！「データ管理」から確認できます。")
        # 保存成功後、df_test_resultsを再ロードして最新の状態にする
        df_test_results = load_data_from_gas(test_results_sheet_name)
    else:
        st.error("テスト結果の保存に失敗しました。")

    if updated_vocab_ids:
        write_success_vocab = write_data_to_gas(df_vocab, current_worksheet_name)
        if write_success_vocab:
            st.success("学習進捗が更新されました！")
        else:
            st.error("学習進捗の更新に失敗しました。")

# ... (以降のStreamlitアプリのロジックは変更なし) ...
