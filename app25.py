# app25.py

import streamlit as st
import pandas as pd
import requests # GASを使用しない場合は不要になるが、今回は残しておく
import json
import os
import random
from datetime import datetime, date
import io

# Supabase connection
from st_supabase_connection import SupabaseConnection

# --- 設定項目 ---
# ★★★ GAS_WEBAPP_URL と GAS_API_KEY はコメントアウトまたは削除 ★★★
# GAS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbzIHdzvPWRgu3uyOb2A1rHQTvpxzU6sLKBm5Ybwt--ozxLFe0_i7nr071RjwjgdkaxGA/exec" 
# GAS_API_KEY = "my_streamlit_secret_key_123" 

# --- Supabaseクライアントの初期化 ---
# st.secrets['SUPABASE_URL'] と st.secrets['SUPABASE_KEY'] を使用
conn = st.connection("supabase", type=SupabaseConnection)

# ヘッダー定義 (テーブル名とカラム名をSupabaseのものに合わせる)
# VOCAB_HEADERS = ['ID', '用語 (Term)', '説明 (Definition)', '例文 (Example)', 'カテゴリ (Category)', '学習進捗 (Progress)']
# TEST_RESULTS_HEADERS = ['Date', 'Category', 'TestType', 'Score', 'TotalQuestions', 'Details']

# Supabaseのテーブル名とカラム名に合わせる
VOCAB_TABLE_NAME = "vocab_data"
VOCAB_COLUMNS = ['id', 'user_name', 'term', 'definition', 'example', 'category', 'progress', 'created_at', 'updated_at']

TEST_RESULTS_TABLE_NAME = "test_results"
TEST_RESULTS_COLUMNS = ['id', 'user_name', 'test_date', 'category', 'test_type', 'score', 'total_questions', 'details']

# Streamlit アプリケーションの開始
st.set_page_config(layout="wide")
st.title("ビジネス用語集ビルダー")

# ... (既存のコードはそのまま) ...
