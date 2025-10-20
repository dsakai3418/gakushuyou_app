# --- テスト結果と学習進捗をGASに書き込む関数 ---
    def save_test_results_and_progress():
        global df_vocab, df_test_results # グローバル変数としてdf_vocabとdf_test_resultsを更新

        questions = st.session_state.test_mode['questions']
        user_answers = st.session_state.test_mode['answers']
        
        final_score = 0
        current_detailed_results = []
        updated_vocab_ids = set() # 今回のテストで進捗が更新されたIDを追跡

        # df_vocabをコピーして操作し、最後に元のdf_vocabに代入する
        temp_df_vocab = df_vocab.copy()

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

            # 学習進捗の更新ロジック (temp_df_vocabを更新)
            # ここでIDの型を確実に合わせる
            # df_vocabのIDは'Int64'型なので、q['term_id']も整数型であることを確認
            if pd.notna(q.get('term_id')):
                term_id_int = int(q['term_id']) # 必ず整数に変換
                original_df_index = temp_df_vocab[temp_df_vocab['ID'] == term_id_int].index
                
                if not original_df_index.empty:
                    row_idx = original_df_index[0]
                    current_progress = temp_df_vocab.loc[row_idx, '学習進捗 (Progress)']
                    
                    if is_correct:
                        if current_progress == 'Not Started':
                            temp_df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Learning'
                        elif current_progress == 'Learning':
                            temp_df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Mastered'
                    else: # 不正解の場合、進捗を戻す
                        if current_progress == 'Mastered':
                            temp_df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Learning'
                        elif current_progress == 'Learning':
                            temp_df_vocab.loc[row_idx, '学習進捗 (Progress)'] = 'Not Started'
                    updated_vocab_ids.add(term_id_int)

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

        new_result_df_row = {
            'Date': test_date_obj,
            'Category': category_used,
            'TestType': test_type_display,
            'Score': final_score,
            'TotalQuestions': len(questions),
            'Details': current_detailed_results # リストとして直接代入
        }
        
        # DataFrame.append は非推奨なので concat を使用
        if df_test_results.empty:
            df_test_results = pd.DataFrame([new_result_df_row], columns=TEST_RESULTS_HEADERS)
        else:
            df_test_results = pd.concat([df_test_results, pd.DataFrame([new_result_df_row])], ignore_index=True)

        # テスト結果を保存
        write_success_results = write_data_to_gas(df_test_results, test_results_sheet_name)
        if write_success_results:
            st.success("テスト結果が保存されました！「データ管理」から確認できます。")
        else:
            st.error("テスト結果の保存に失敗しました。")

        # 学習進捗を保存
        if updated_vocab_ids:
            # テンポラリDataFrameからdf_vocabを更新
            df_vocab = temp_df_vocab 
            write_success_vocab = write_data_to_gas(df_vocab, current_worksheet_name)
            if write_success_vocab:
                st.success("学習進捗が更新されました！")
            else:
                st.error("学習進捗の更新に失敗しました。")
