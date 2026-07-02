# troubleshooting_guide.py

class TroubleshootingGuide:
    """故障排查指南"""
    
    ISSUES = {
        'vocal_layer_not_responding': {
            'symptoms': [
                '返回空字符串',
                '返回原始 draft_response',
                '日誌中無 finalize_voice 記錄'
            ],
            'causes': [
                'VocalPersonalityLayer 未初始化',
                'dependencies 未注入',
                'island_fusion 或 heretic_coordinator 為 None'
            ],
            'solutions': [
                '檢查 PersonalityModule.setup_dependencies() 是否調用',
                '驗證 VocalPersonalityLayer 實例化',
                '檢查日誌中 "VocalPersonalityLayer v1.0 initialized" 消息'
            ]
        },
        'particles_not_injected': {
            'symptoms': [
                '輸出中無粵語粒子',
                '回應聽起來像機器翻譯',
                'PERSONALITY_PARTICLES 計數為 0'
            ],
            'causes': [
                '_inject_particles() 隨機選擇失敗',
                'CANTONESE_PARTICLES_BY_ISLAND 缺少島嶼',
                'Cantonese 詞典加載失敗'
            ],
            'solutions': [
                '檢查隨機概率設置（通常 0.4-0.7）',
                '驗證島嶼名稱是否在 CANTONESE_PARTICLES_BY_ISLAND 中',
                '執行 cantonese_dict.get_dict_stats() 驗證詞典狀態'
            ]
        },
        'sentences_too_long': {
            'symptoms': [
                '輸出超過 3 句',
                '字數超過 200',
                'sentence_splits 計數為 0'
            ],
            'causes': [
                '_enforce_short_sentences() 分割失敗',
                '正則表達式未匹配標點符號',
                'max_sentences 限制未生效'
            ],
            'solutions': [
                '檢查 SENTENCE_TERMINATORS 是否完整',
                '測試正則表達式 split 邏輯',
                '增加日誌以追蹤分割過程'
            ]
        },
        'island_tone_not_applied': {
            'symptoms': [
                '無論島嶼如何，輸出都相同',
                'island_adjustments 計數為 0',
                '測試中島嶼特定詞彙未出現'
            ],
            'causes': [
                '_apply_island_tone() 未被調用',
                'primary_island 值為 "Unknown"',
                '替換邏輯失敗'
            ],
            'solutions': [
                '驗證 island_fusion.calculate_activation() 結果',
                '檢查 primary_island 是否正確傳遞',
                '測試字符串替換邏輯'
            ]
        },
        'circular_dependencies': {
            'symptoms': [
                'ImportError: circular import',
                'AttributeError: module X has no attribute Y',
                '初始化時掛起'
            ],
            'causes': [
                'vocal_personality_layer 導入 island_fusion',
                'island_fusion 反向導入 vocal_personality_layer',
                '延遲導入未正確處理'
            ],
            'solutions': [
                '檢查 import 語句',
                '使用延遲導入 (import inside function)',
                '重構相互依賴的模組'
            ]
        }
    }
    
    @staticmethod
    def diagnose(symptom_key: str) -> Dict:
        """診斷問題"""
        if symptom_key in TroubleshootingGuide.ISSUES:
            return TroubleshootingGuide.ISSUES[symptom_key]
        return {'error': '未知問題'}
    
    @staticmethod
    def print_all_issues():
        """列印所有可能的問題"""
        print("\n" + "="*70)
        print("故障排查指南")
        print("="*70)
        
        for issue_key, issue_data in TroubleshootingGuide.ISSUES.items():
            print(f"\n問題: {issue_key}")
            print(f"症狀:")
            for symptom in issue_data['symptoms']:
                print(f"  - {symptom}")
            print(f"可能原因:")
            for cause in issue_data['causes']:
                print(f"  - {cause}")
            print(f"解決方案:")
            for solution in issue_data['solutions']:
                print(f"  - {solution}")