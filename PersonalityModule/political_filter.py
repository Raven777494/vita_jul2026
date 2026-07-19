# PersonalityModule/political_filter.py
# 敏感內容檢測系統 v2.0 (修正版)

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime

from .utils.logger import get_logger

logger = get_logger('personality')


class PoliticalFilter:
    """
    敏感內容檢測系統 v2.0

    修正清單:
    [FIXED-PF1] 完善參數驗證
    [FIXED-PF2] 改善敏感詞搜尋效能
    [FIXED-PF3] 統一返回格式
    [FIXED-PF4] 強化例外處理
    """

    def __init__(self, config: Dict = None, data_dir: str = './data'):
        """
        初始化敏感詞過濾器

        Args:
            config: 配置字典（可選）
            data_dir: 數據目錄
        """
        self.logger = logger
        self.data_dir = Path(data_dir)

        # 從配置加載敏感詞
        self.sensitivity_keywords = self._load_sensitivity_keywords(config)

        # 若無外部檔案，使用內置詞庫
        if not self.sensitivity_keywords:
            self.sensitivity_keywords = self._get_default_keywords()

        self.logger.info(f"PoliticalFilter initialized with {self._count_keywords()} keywords")

    def _load_sensitivity_keywords(self, config: Optional[Dict]) -> Dict:
        """
        [FIXED-PF1] 加載敏感詞庫

        優先級：
        1. 外部檔案
        2. 配置對象
        3. 內置預設
        """
        # 嘗試從檔案加載
        keywords_file = self.data_dir / 'sensitivity_keywords.json'

        if keywords_file.exists():
            try:
                with open(keywords_file, 'r', encoding='utf-8') as f:
                    keywords = json.load(f)
                self.logger.info(f"Loaded keywords from file: {keywords_file}")
                return keywords
            except Exception as e:
                self.logger.warning(f"Failed to load from file: {e}")

        # 嘗試從配置加載
        if config and isinstance(config, dict):
            try:
                keywords = {
                    'political': {
                        'tier1': config.get('tier1_critical_keywords', []),
                        'tier2': config.get('tier2_sensitive_keywords', []),
                        'tier3': config.get('tier3_minor_keywords', [])
                    },
                    'self_harm': config.get('self_harm_keywords', []),
                    'violence': config.get('violence_keywords', []),
                    'sexual': config.get('sexual_keywords', []),
                    'harassment': config.get('harassment_keywords', [])
                }
                if any(keywords.values()):
                    self.logger.info("Loaded keywords from config")
                    return keywords
            except Exception as e:
                self.logger.debug(f"Failed to load from config: {e}")

        return {}

    def _get_default_keywords(self) -> Dict:
        """取得預設敏感詞庫"""
        return {
            'political': {
                'tier1': [
                    '習近平', '中共', '天安門', '六四', '臺獨', '港獨',
                    'Xi Jinping', 'CCP', 'Tiananmen', '6/4'
                ],
                'tier2': [
                    '國安法', '新疆', '西藏', '示威', '抗爭',
                    '維吾爾', '藏獨', '法輪功', '民運'
                ],
                'tier3': [
                    '政府', '民主', '自由', '革命', '威權',
                    '獨裁', '壓迫', '監控'
                ]
            },
            'self_harm': [
                '自殺', '割腕', '上吊', '絕望', '活著沒意義',
                '不想活', '想死', '往死裡', '尋死',
                '安樂死', '自我傷害'
            ],
            'violence': [
                '殺人', '血', '砍', '打死', '毆打',
                '刺死', '槍殺', '爆炸', '恐怖',
                '暴力', '血腥'
            ],
            'sexual': [
                '色情', '鹹濕', '奸', '強姦', '性侵',
                '成人內容', '裸', '淫穢', '猥褻',
                '發情', '做愛'
            ],
            'harassment': [
                '滾', '傻', '垃圾', '廢物', '死人',
                '傷害', '騷擾', '威脅', '辱罵'
            ]
        }

    def _count_keywords(self) -> int:
        """計算關鍵詞總數"""
        total = 0
        for category, content in self.sensitivity_keywords.items():
            if isinstance(content, dict):
                total += sum(len(v) if isinstance(v, list) else 0 for v in content.values())
            elif isinstance(content, list):
                total += len(content)
        return total

    def detect_sensitivity(
        self,
        response: str,
        user_input: str
    ) -> Dict:
        """
        [FIXED-PF3] 【核心方法】檢測敏感內容

        Args:
            response: 希兒的回應
            user_input: 用戶輸入

        Returns:
            {
                'is_sensitive': bool,
                'category': str,
                'risk_level': str,
                'triggered_keywords': List[str],
                'source': str,
                'recommendation': str
            }
        """
        try:
            # [FIXED-PF1] 參數驗證
            response = str(response or '')
            user_input = str(user_input or '')

            # 檢查回應
            response_result = self._check_text(response)

            # 檢查用戶輸入
            user_result = self._check_text(user_input)

            # [FIXED-PF3] 統一返回格式
            if response_result['is_sensitive'] and user_result['is_sensitive']:
                combined_risk = self._get_max_risk_level(
                    response_result['risk_level'],
                    user_result['risk_level']
                )
                source = 'both'

            elif response_result['is_sensitive']:
                combined_risk = response_result['risk_level']
                response_result['keywords'] = response_result['keywords']
                user_result['keywords'] = []
                source = 'response'

            elif user_result['is_sensitive']:
                combined_risk = user_result['risk_level']
                response_result['keywords'] = []
                user_result['keywords'] = user_result['keywords']
                source = 'user_input'

            else:
                return {
                    'is_sensitive': False,
                    'category': 'safe',
                    'risk_level': 'safe',
                    'triggered_keywords': [],
                    'source': 'none',
                    'recommendation': 'allow'
                }

            # 決定建議
            if combined_risk in ['tier1', 'critical']:
                recommendation = 'block'
            elif combined_risk == 'tier2':
                recommendation = 'rewrite'
            else:
                recommendation = 'allow'

            result = {
                'is_sensitive': True,
                'category': response_result['category'] or user_result['category'],
                'risk_level': combined_risk,
                'triggered_keywords': list(set(
                    response_result.get('keywords', []) +
                    user_result.get('keywords', [])
                )),
                'source': source,
                'recommendation': recommendation
            }

            if result['is_sensitive']:
                self.logger.warning(
                    f"Sensitivity detected: {result['category']} "
                    f"(risk: {result['risk_level']}, source: {result['source']})"
                )

            return result

        except Exception as e:
            # Fail-safe：分類器故障時不可預設放行。用 tier2/rewrite 觸發降級改寫，
            # 避免誤用 tier1 把一般故障全變成危機固定句。
            self.logger.error(f"Detection failed: {e}", exc_info=True)
            return {
                'is_sensitive': True,
                'category': 'unknown',
                'risk_level': 'tier2',
                'triggered_keywords': [],
                'source': 'detector_error',
                'recommendation': 'rewrite',
                'error': str(e),
            }

    def _check_text(self, text: str) -> Dict:
        """
        [FIXED-PF2] 檢查單個文本

        Returns:
            {
                'is_sensitive': bool,
                'category': str,
                'risk_level': str,
                'keywords': List[str]
            }
        """
        if not text:
            return {
                'is_sensitive': False,
                'category': 'safe',
                'risk_level': 'safe',
                'keywords': []
            }

        triggered = []
        keywords = self.sensitivity_keywords

        # [FIXED-PF2] 統一的搜尋邏輯
        categories_to_check = [
            ('political', 'tier', ['tier1', 'tier2', 'tier3']),
            ('self_harm', 'direct', []),
            ('violence', 'direct', []),
            ('sexual', 'direct', []),
            ('harassment', 'direct', [])
        ]

        for category, check_type, subcategories in categories_to_check:
            if category not in keywords:
                continue

            if check_type == 'tier':
                for tier in subcategories:
                    if tier in keywords[category]:
                        for word in keywords[category][tier]:
                            if word in text:
                                triggered.append({
                                    'word': word,
                                    'category': category,
                                    'tier': tier
                                })

            else:  # direct
                for word in keywords.get(category, []):
                    if word in text:
                        # [FIXED-PF1] 確定風險等級
                        if category == 'self_harm' or category == 'violence':
                            tier = 'tier1'
                        elif category == 'sexual':
                            tier = 'tier2'
                        else:
                            tier = 'tier3'

                        triggered.append({
                            'word': word,
                            'category': category,
                            'tier': tier
                        })

        if not triggered:
            return {
                'is_sensitive': False,
                'category': 'safe',
                'risk_level': 'safe',
                'keywords': []
            }

        # 決定最高風險等級
        max_tier = self._get_max_tier([t['tier'] for t in triggered])
        category = triggered[0]['category']

        return {
            'is_sensitive': True,
            'category': category,
            'risk_level': max_tier,
            'keywords': [t['word'] for t in triggered]
        }

    def _get_max_tier(self, tiers: List[str]) -> str:
        """[FIXED-PF1] 取得最高等級"""
        tier_levels = {'critical': 4, 'tier1': 3, 'tier2': 2, 'tier3': 1, 'safe': 0}

        if not tiers:
            return 'safe'

        return max(tiers, key=lambda t: tier_levels.get(t, 0))

    def _get_max_risk_level(self, risk1: str, risk2: str) -> str:
        """[FIXED-PF1] 取得最高風險等級"""
        return self._get_max_tier([risk1, risk2])

    def get_filter_stats(self) -> Dict:
        """[FIXED-PF4] 取得過濾器統計"""
        try:
            categories = {}
            for category, content in self.sensitivity_keywords.items():
                if isinstance(content, dict):
                    count = sum(len(v) if isinstance(v, list) else 0 for v in content.values())
                elif isinstance(content, list):
                    count = len(content)
                else:
                    count = 0
                categories[category] = count

            return {
                'total_keywords': sum(categories.values()),
                'categories': categories,
                'loaded_from': 'file' if (self.data_dir / 'sensitivity_keywords.json').exists() else 'default'
            }

        except Exception as e:
            self.logger.error(f"Failed to get stats: {e}")
            return {
                'total_keywords': 0,
                'categories': {},
                'error': str(e)
            }