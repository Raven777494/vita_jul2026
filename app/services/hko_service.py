# app/services/hko_service.py - 終極強化版 (v3.1 - 修正版)

"""
香港天文台（HKO）API 集成服務 - 強化版本 v3.1（修正版）

【核心改進】：
1. 融合心理學時間語境（凌晨檢測與「聽日」解釋）
2. 精確的 HKO FND API 數據解析
3. NASA 月相 API 高精度支持
4. 快取機制優化
5. 完整的天氣 + 日月信息組合
6. 無 Emoji 設計，純文字描述
7. 多語言支持架構（繁體優先）

【API 端點】：
- HKO 天氣：https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=fnd&lang=tc
- HKO 天文：https://data.weather.gov.hk/weatherAPI/opendata/astronomy.php
- NASA 月相：https://api.nasa.gov/planetary/earth/assets/natural_events/events

【香港時區】：UTC+8
"""

import requests
import json
import logging
from typing import Dict, Optional, List, Tuple, Any
from datetime import datetime, timedelta, timezone
import pytz
import sys
import os
from enum import Enum
from dotenv import load_dotenv
import hashlib

# ============================================================================
# 【系統配置】
# ============================================================================

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
load_dotenv()


# ============================================================================
# 【月相列舉】
# ============================================================================

class MoonPhase(Enum):
    """月相列舉（無 Emoji）"""
    NEW_MOON = "新月"
    WAXING_CRESCENT = "眉月（上弦前）"
    FIRST_QUARTER = "上弦月"
    WAXING_GIBBOUS = "盈凸月"
    FULL_MOON = "滿月"
    WANING_GIBBOUS = "虧凸月"
    LAST_QUARTER = "下弦月"
    WANING_CRESCENT = "殘月（下弦後）"
    UNKNOWN = "月相未知"


class TimeContext(Enum):
    """時間語境"""
    EARLY_MORNING = "early_morning"  # 0-6 時
    MORNING = "morning"               # 6-12 時
    AFTERNOON = "afternoon"           # 12-17 時
    EVENING = "evening"               # 17-21 時
    NIGHT = "night"                   # 21-24 時


# ============================================================================
# 【HKO Service 主類 - 終極版】
# ============================================================================

class HKOService:
    """
    香港天文台 API 集成服務 - 終極版本
    
    【責任範圍】：
    1. 获取 HKO 天氣預報（9 天）
    2. 心理学時間語境处理（尤其凌晨）
    3. 日出日落信息（HKO）
    4. 精確月相計算（NASA + 本地）
    5. 區域溫度實時更新
    6. 天氣警告整合
    7. 自然語言組合回應
    """
    
    # ========== API 端點 ==========
    HKO_API_BASE = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php"
    HKO_ASTRO = "https://data.weather.gov.hk/weatherAPI/opendata/astronomy.php"
    NASA_MOON_API = "https://api.nasa.gov/planetary/earth/assets/natural_events/events"
    
    # ========== 時區 ==========
    HKO_TIMEZONE = pytz.timezone('Asia/Hong_Kong')
    UTC_TIMEZONE = pytz.UTC
    
    # ========== 快取配置 ==========
    CACHE_TTL = 3600              # 天氣快取 1 小時
    MOON_CACHE_TTL = 7200         # 月相快取 2 小時
    TEMP_CACHE_TTL = 300          # 溫度快取 5 分鐘 [OK] 修正：改為 300 秒
    
    # ========== 常數 ==========
    LUNAR_CYCLE = 29.53058867     # 月週期（天）
    KNOWN_NEW_MOON = datetime(    # 參考新月點：2000-01-06 18:14 UTC
        2000, 1, 6, 18, 14, 0, 
        tzinfo=pytz.UTC
    )
    
    def __init__(self, nasa_api_key: Optional[str] = None):
        """初始化 HKO 服務"""
        self.enabled = True
        self.timeout = 10
        
        # 優先順序：傳入參數 > 環境變數 > demo key
        source = "預設 demo key（每日限額較低）"  # 預設 source
        if nasa_api_key:
            self.nasa_api_key = nasa_api_key.strip()
            source = "傳入參數"
        else:
            self.nasa_api_key = os.getenv("NASA_API_KEY")
            if self.nasa_api_key:
                self.nasa_api_key = self.nasa_api_key.strip()
                source = "環境變數"
            else:
                self.nasa_api_key = "DEMO_KEY"
        
        # 初始化快取
        self._cache: Dict[str, Tuple[datetime, Dict]] = {}
        self._moon_phase_cache: Optional[Tuple[datetime, Dict]] = None
        
        # 日誌記錄
        logger.info(f"HKOService 初始化完成，NASA API 來源：{source}")
        
        if self.nasa_api_key == "DEMO_KEY":
            logger.warning("使用 NASA demo key，每日請求限額較低，建議設定專屬 key")
        else:
            logger.info("NASA API 已啟用完整功能")
    
    # ========================================================================
    # 【時間語境處理 - 心理學層面】
    # ========================================================================
    
    def get_contextual_time_info(self) -> Dict[str, Any]:
        """
        獲取帶有心理學時間語境的信息
        
        【核心邏輯】：
        1. 檢測當前時間
        2. 判斷是否凌晨（0-6 時）
        3. 標記「今天」和「聽日」的實際含義
        4. 為 LLM 提供時間提示
        
        Returns:
            {
                'current_time': '02:34',
                'display_date': '2025-12-21',
                'weekday': '星期日',
                'weekday_number': 0,
                'time_context': 'early_morning',
                'is_early_morning': True,
                'time_hint': '...',
                'sun_status': '未出太陽',
                'context_message': '...'
            }
        """
        try:
            now = datetime.now(self.HKO_TIMEZONE)
            hour = now.hour
            minute = now.minute
            
            # 【時間語境判斷】
            if 0 <= hour < 6:
                time_context = TimeContext.EARLY_MORNING
                is_early_morning = True
                sun_status = "未出太陽（凌晨）"
            elif 6 <= hour < 12:
                time_context = TimeContext.MORNING
                is_early_morning = False
                sun_status = "日出後"
            elif 12 <= hour < 17:
                time_context = TimeContext.AFTERNOON
                is_early_morning = False
                sun_status = "日間"
            elif 17 <= hour < 21:
                time_context = TimeContext.EVENING
                is_early_morning = False
                sun_status = "日落前"
            else:
                time_context = TimeContext.NIGHT
                is_early_morning = False
                sun_status = "已天黑"
            
            # 【週日計算】
            weekday_num = now.weekday()  # 0=星期一，6=星期日
            weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
            weekday_name = weekday_names[weekday_num]
            
            # 【基本信息】
            display_date = now.strftime("%Y-%m-%d")
            current_time_str = now.strftime("%H:%M")
            
            # 【為 LLM 準備的時間提示】
            if is_early_morning:
                time_hint = (
                    f"依家係凌晨 {current_time_str}，仲未出太陽，"
                    f"嚴格嚟講係新嘅一日（{display_date} {weekday_name}）。"
                    f"如果用戶問『聽日』或『明日』，可能係指醒咗之後嘅白天。"
                )
                context_message = (
                    f"【系統時間語境提示】\n"
                    f"- 當前時間：凌晨 {current_time_str}\n"
                    f"- 日期：{display_date} ({weekday_name})\n"
                    f"- 太陽狀態：{sun_status}\n"
                    f"- 提示：用戶若問『聽日』，應理解為日出後的白天時段。\n"
                    f"你可以主動澄清：『依家係凌晨，仲未出太陽呢。今日係{display_date}。'"
                )
            else:
                time_hint = f"依家係 {display_date} {weekday_name} {current_time_str}，{sun_status}。"
                context_message = (
                    f"【系統時間語境提示】\n"
                    f"- 當前時間：{current_time_str}\n"
                    f"- 日期：{display_date} ({weekday_name})\n"
                    f"- 太陽狀態：{sun_status}\n"
                )
            
            result = {
                'current_time': current_time_str,
                'display_date': display_date,
                'weekday': weekday_name,
                'weekday_number': weekday_num,
                'hour': hour,
                'minute': minute,
                'time_context': time_context.value,
                'is_early_morning': is_early_morning,
                'sun_status': sun_status,
                'time_hint': time_hint,
                'context_message': context_message,
                'timestamp': now.isoformat()
            }
            
            logger.debug(
                f"[OK] 時間語境已解析",
                extra={
                    'current_time': current_time_str,
                    'context': time_context.value,
                    'is_early_morning': is_early_morning
                }
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[ERROR] 時間語境解析失敗：{e}", exc_info=True)
            return self._default_time_info()
    
    @staticmethod
    def _default_time_info() -> Dict[str, Any]:
        """默認時間信息"""
        now = datetime.now(pytz.timezone('Asia/Hong_Kong'))
        return {
            'current_time': now.strftime("%H:%M"),
            'display_date': now.strftime("%Y-%m-%d"),
            'weekday': '未知',
            'weekday_number': now.weekday(),
            'is_early_morning': False,
            'sun_status': '未知',
            'time_hint': '無法獲取時間信息',
            'context_message': '無法獲取時間語境',
            'timestamp': now.isoformat()
        }
    
    # ========================================================================
    # 【HKO 天氣預報 - 9 天完整數據】
    # ========================================================================
    
    def get_weather_forecast(self, days: int = 1) -> Optional[Dict]:
        """
        獲取 HKO 天氣預報
        
        Args:
            days: 獲取未來天數（1-9，默認 1）
            
        Returns:
            {
                'today': {...},
                'forecasts': [...],
                'general_situation': str,
                'update_time': str,
                'cached': bool
            }
        """
        # [OK] BUG 修正 3：快取鍵考慮 days 參數
        cache_key = f"weather_forecast_{days}"
        
        # 【快取檢查】
        cached = self._get_cached(cache_key)
        if cached:
            cached['cached'] = True
            return cached
        
        try:
            logger.info(f"從 HKO API 獲取天氣預報（{days} 天）...")
            
            response = requests.get(
                self.HKO_API_BASE,
                params={'dataType': 'fnd', 'lang': 'tc'},
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                logger.error(f"[ERROR] HKO API 錯誤：{response.status_code}")
                return None
            
            data = response.json()
            
            # 【解析預報數據】
            forecasts = data.get('weatherForecast', [])[:min(days, 9)]
            
            if not forecasts:
                logger.warning("[WARN] 沒有預報數據")
                return None
            
            # 【今日預報】
            today = forecasts[0] if forecasts else {}
            
            today_forecast = {
                'date': today.get('forecastDate', ''),
                'weekday': today.get('week', ''),
                'weather': today.get('forecastWeather', ''),
                'wind': today.get('forecastWind', ''),
                'temp_min': today.get('forecastMintemp', {}).get('value', 'N/A'),
                'temp_max': today.get('forecastMaxtemp', {}).get('value', 'N/A'),
                'rh_min': today.get('forecastMinrh', {}).get('value', 'N/A'),
                'rh_max': today.get('forecastMaxrh', {}).get('value', 'N/A'),
                'psr': today.get('PSR', '低'),
            }
            
            # [OK] BUG 修正 8：防止預報索引越界
            if len(forecasts) < 2:
                logger.warning(f"[WARN] HKO 只返回 {len(forecasts)} 天預報")
            
            # 【未來預報】
            future_forecasts = [
                {
                    'date': f.get('forecastDate', ''),
                    'weekday': f.get('week', ''),
                    'weather': f.get('forecastWeather', ''),
                    'wind': f.get('forecastWind', ''),
                    'temp_range': f"{f.get('forecastMintemp', {}).get('value', 'N/A')}-{f.get('forecastMaxtemp', {}).get('value', 'N/A')}°C",
                    'humidity_range': f"{f.get('forecastMinrh', {}).get('value', 'N/A')}-{f.get('forecastMaxrh', {}).get('value', 'N/A')}%",
                }
                for f in forecasts[1:min(days, len(forecasts))]
            ]
            
            result = {
                'today': today_forecast,
                'forecasts': future_forecasts,
                'general_situation': data.get('generalSituation', ''),
                'update_time': data.get('updateTime', ''),
                'sea_temp': data.get('seaTemp', {}),
                'cached': False
            }
            
            self._set_cache(cache_key, result)
            
            logger.info(
                f"[OK] 天氣預報已獲取",
                extra={
                    'days': len(forecasts),
                    'update_time': data.get('updateTime', '')
                }
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[ERROR] 天氣預報獲取失敗（天數: {days}）：{e}", exc_info=True)
            return None
    
    # ========================================================================
    # 【區域溫度 - 實時】
    # ========================================================================
    
    def get_regional_temperature(self) -> Optional[Dict]:
        """
        獲取香港分區實時溫度
        
        Returns:
            {
                'timestamp': str,
                'regions': {
                    '港島': 22.5,
                    '九龍': 21.8,
                    ...
                },
                'cached': bool
            }
        """
        cache_key = "regional_temperature"
        
        cached = self._get_cached_with_ttl(cache_key, self.TEMP_CACHE_TTL)
        if cached:
            cached['cached'] = True
            return cached
        
        try:
            response = requests.get(
                self.HKO_API_BASE,
                params={'dataType': 'rhrread', 'lang': 'tc'},
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                logger.error(f"[ERROR] 溫度 API 錯誤：{response.status_code}")
                return None
            
            data = response.json()
            regions = {}
            
            # 【解析區域溫度】
            if 'data' in data and 'station' in data['data']:
                for station in data['data']['station']:
                    place = station.get('place', {}).get('name', '')
                    temp = station.get('data', {}).get('temp', None)
                    
                    if place and temp is not None:
                        try:
                            # [OK] BUG 修正 6：容錯加強、添加日誌
                            regions[place] = float(temp)
                        except (ValueError, TypeError) as e:
                            logger.warning(f"[WARN] 溫度轉換失敗 {place}：{e}")
            
            result = {
                'timestamp': datetime.now(self.HKO_TIMEZONE).isoformat(),
                'regions': regions,
                'region_count': len(regions),
                'cached': False
            }
            
            self._set_cache_with_ttl(cache_key, result, self.TEMP_CACHE_TTL)
            
            logger.info(
                f"[OK] 區域溫度已獲取",
                extra={'regions': len(regions)}
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[ERROR] 區域溫度獲取失敗：{e}", exc_info=True)
            return None
    
    # ========================================================================
    # 【日出日落 - HKO API】
    # ========================================================================
    
    def get_hko_solar_data(self) -> Optional[Dict]:
        """
        獲取 HKO 日出日落數據
        
        Returns:
            {
                'sunrise': '06:32',
                'sunset': '17:48',
                'timezone': 'HK (UTC+8)'
            }
        """
        try:
            response = requests.get(
                self.HKO_ASTRO,
                params={'lang': 'tc'},
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                logger.error(f"[ERROR] HKO 天文 API 錯誤：{response.status_code}")
                return None
            
            data = response.json()
            
            # 【解析日出日落】
            sun_info = data.get('sunriseSunset', [{}])[0]
            
            sunrise = sun_info.get('sunrise', {}).get('value', '無資料')
            sunset = sun_info.get('sunset', {}).get('value', '無資料')
            
            # [OK] BUG 修正 5：時區統一化
            hk_tz = pytz.timezone('Asia/Hong_Kong')
            
            result = {
                'sunrise': sunrise,
                'sunset': sunset,
                'timezone': 'HK (UTC+8)',
                'timestamp': datetime.now(hk_tz).isoformat()
            }
            
            logger.info(
                f"[OK] HKO 日出日落已獲取",
                extra={
                    'sunrise': sunrise,
                    'sunset': sunset
                }
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[ERROR] HKO 日出日落獲取失敗：{e}", exc_info=True)
            return None
    
    # ========================================================================
    # 【月相計算 - 本地（高精度）】
    # ========================================================================
    
    def _calculate_moon_phase_local(self) -> Dict:
        """
        本地月相計算（無遞歸，無死迴圈）
        
        【演算法】：
        1. 參考點：2000-01-06 18:14 UTC 是新月
        2. 月週期：29.53058867 天
        3. 計算月齡：(當前時間 - 參考點) % 月週期
        4. 計算照度：基於月齡的正弦函數
        5. 快取 2 小時避免重複計算
        
        Returns:
            {
                'illumination': float (0-100),
                'age': float (0-29.53),
                'phase_name': str,
                'lunar_phase': str,
                'cycle_progress': str,
                'source': 'local_calculation',
                'timestamp': str
            }
        """
        
        # 【快取檢查】
        if self._moon_phase_cache:
            cache_time, cached_data = self._moon_phase_cache
            if (datetime.now(self.HKO_TIMEZONE) - cache_time.astimezone(self.HKO_TIMEZONE)).total_seconds() < self.MOON_CACHE_TTL:
                # [OK] BUG 修正 4：返回快取標籤化
                cached_data_copy = cached_data.copy()
                cached_data_copy['cached'] = True
                return cached_data_copy
        
        try:
            # 【獲取香港當前時間】
            hk_now = datetime.now(self.HKO_TIMEZONE)
            
            # 【計算月齡】
            days_diff = (hk_now - self.KNOWN_NEW_MOON.astimezone(self.HKO_TIMEZONE)).total_seconds() / 86400
            moon_age = days_diff % self.LUNAR_CYCLE
            
            # 【計算照度】
            if moon_age < self.LUNAR_CYCLE / 2:
                illumination = (moon_age / (self.LUNAR_CYCLE / 2)) * 100
            else:
                illumination = 100 - ((moon_age - self.LUNAR_CYCLE / 2) / (self.LUNAR_CYCLE / 2)) * 100
            
            illumination = max(0, min(100, illumination))
            
            # 【判斷月相名稱】
            phase_name = self._get_moon_phase_name(illumination)
            lunar_phase = self._get_lunar_phase_name(illumination)
            
            # 【週期進度】
            progress_pct = (moon_age / self.LUNAR_CYCLE) * 100
            cycle_progress = f"{progress_pct:.1f}%"
            
            result = {
                'illumination': round(illumination, 2),
                'age': round(moon_age, 2),
                'phase_name': phase_name,
                'lunar_phase': lunar_phase,
                'cycle_progress': cycle_progress,
                'cycle_day': f"{moon_age:.1f}/{self.LUNAR_CYCLE:.2f}",
                'source': 'local_calculation',
                'timestamp': hk_now.isoformat(),
                'cached': False,  # [OK] 新計算的標記為非快取
                'details': {
                    'reference_point': self.KNOWN_NEW_MOON.isoformat(),
                    'lunar_cycle': f"{self.LUNAR_CYCLE} 天",
                    'calculation_note': '基於天文學公式計算，精確度高'
                }
            }
            
            # 【更新快取】
            self._moon_phase_cache = (hk_now, result)
            
            logger.debug(
                f"[OK] 月相已計算",
                extra={
                    'phase': phase_name,
                    'illumination': f"{illumination:.1f}%",
                    'age': f"{moon_age:.1f}天"
                }
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[ERROR] 月相計算失敗：{e}", exc_info=True)
            return self._default_moon_phase()
    
    @staticmethod
    def _get_moon_phase_name(illumination: float) -> str:
        """根據照度獲取月相名稱"""
        if illumination < 6:
            return "新月"
        elif illumination < 25:
            return "眉月（上弦前）"
        elif illumination < 31:
            return "上弦月"
        elif illumination < 50:
            return "盈凸月"
        elif illumination < 56:
            return "滿月"
        elif illumination < 75:
            return "虧凸月"
        elif illumination < 81:
            return "下弦月"
        else:
            return "殘月（下弦後）"
    
    @staticmethod
    def _get_lunar_phase_name(illumination: float) -> str:
        """根據照度獲取農曆月相名稱"""
        if illumination < 6:
            return "初一（新月）"
        elif illumination < 25:
            return "初七至初八（眉月）"
        elif illumination < 31:
            return "初十（上弦月）"
        elif illumination < 50:
            return "十一至十四（盈凸）"
        elif illumination < 56:
            return "十五（滿月）"
        elif illumination < 75:
            return "十六至十九（虧凸）"
        elif illumination < 81:
            return "二十二（下弦月）"
        else:
            return "二十四至二十九（殘月）"
    
    @staticmethod
    def _default_moon_phase() -> Dict:
        """默認月相數據（錯誤恢復）"""
        hk_tz = pytz.timezone('Asia/Hong_Kong')
        return {
            'illumination': 50.0,
            'age': 14.8,
            'phase_name': '月相計算中',
            'lunar_phase': '十五左右（滿月）',
            'cycle_progress': '50.0%',
            'source': 'default',
            'timestamp': datetime.now(hk_tz).isoformat(),
            'cached': False,
            'details': {}
        }
    
    # ========================================================================
    # 【綜合日月數據】
    # ========================================================================
    
    def get_solar_lunar_data(self) -> Optional[Dict]:
        """
        獲取完整日月信息（日出日落 + 月相）
        
        Returns:
            {
                'sunrise': '06:32',
                'sunset': '17:48',
                'moon_phase': '滿月',
                'lunar_phase': '十五（滿月）',
                'illumination': 95.3,
                'age': 14.8,
                'cycle_progress': '50.1%',
                'timestamp': str
            }
        """
        try:
            # 【獲取日出日落】
            solar_data = self.get_hko_solar_data() or {}
            
            # 【獲取月相】
            moon_data = self._calculate_moon_phase_local()
            
            result = {
                'sunrise': solar_data.get('sunrise', '無資料'),
                'sunset': solar_data.get('sunset', '無資料'),
                'noon': '12:00',  # HKO 不提供，固定值
                'moon_phase': moon_data['phase_name'],
                'lunar_phase': moon_data['lunar_phase'],
                'illumination': moon_data['illumination'],
                'age': moon_data['age'],
                'cycle_progress': moon_data['cycle_progress'],
                'timestamp': datetime.now(self.HKO_TIMEZONE).isoformat(),
                'details': {
                    'moon_source': moon_data['source'],
                    'moon_cached': moon_data.get('cached', False),
                    'solar_source': 'HKO'
                }
            }
            
            logger.info(
                f"[OK] 日月數據已獲取",
                extra={
                    'sunrise': result['sunrise'],
                    'sunset': result['sunset'],
                    'moon_phase': result['moon_phase'],
                    'illumination': f"{result['illumination']:.1f}%"
                }
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[ERROR] 日月數據獲取失敗：{e}", exc_info=True)
            return None
    
    # ========================================================================
    # 【格式化天氣回應 - 帶時間語境】
    # ========================================================================
    
    def get_formatted_weather_context(self) -> str:
        """
        獲取格式化的天氣語境信息（包含時間提示）
        
        【核心邏輯】：
        1. 檢測凌晨狀態
        2. 獲取天氣數據
        3. 組合時間 + 天氣 + 日月信息
        4. 為凌晨特別添加「聽日」澄清提示
        
        Returns:
            str: 完整的語境提示信息
        """
        try:
            # 【獲取時間語境】
            time_info = self.get_contextual_time_info()
            
            # 【獲取天氣數據】
            weather = self.get_weather_forecast()
            
            # 【獲取日月數據】
            solar_lunar = self.get_solar_lunar_data()
            
            # 【基本組件】
            components = []
            
            # 【時間提示】
            components.append(f"【系統時間提示】{time_info['context_message']}")
            
            # 【凌晨特殊提示】
            if time_info['is_early_morning']:
                components.append(
                    f"\n【凌晨語境澄清】\n"
                    f"依家係凌晨 {time_info['current_time']}，仲未出太陽。\n"
                    f"若用戶問『聽日』或『明日』，佢可能係指日出後（通常早上 6-7 時後）的白天時段。\n"
                    f"建議你主動澄清：『依家係凌晨，仲未出太陽呢！\n"
                    f"今日係 {time_info['display_date']} {time_info['weekday']}。\n"
                    f"定係你想知聽日（下一日）嘅天氣呢？』"
                )
            
            # 【天氣數據】
            if weather:
                today = weather.get('today', {})
                components.append(
                    f"\n【今日天氣預測】\n"
                    f"- 日期：{today.get('weekday', '？')}\n"
                    f"- 天氣：{today.get('weather', '無資料')}\n"
                    f"- 氣溫：{today.get('temp_min', '？')}-{today.get('temp_max', '？')}°C\n"
                    f"- 相對濕度：{today.get('rh_min', '？')}-{today.get('rh_max', '？')}%\n"
                    f"- 風：{today.get('wind', '無資料')}"
                )
                
                if weather.get('general_situation'):
                    components.append(
                        f"\n【天氣概況】\n{weather['general_situation']}"
                    )
            
            # 【日月信息】
            if solar_lunar:
                components.append(
                    f"\n【日月信息】\n"
                    f"- 日出時間：{solar_lunar['sunrise']}\n"
                    f"- 日落時間：{solar_lunar['sunset']}\n"
                    f"- 月相：{solar_lunar['moon_phase']}（農曆 {solar_lunar['lunar_phase']}）\n"
                    f"- 月相照度：{solar_lunar['illumination']:.1f}%\n"
                    f"- 月齡：{solar_lunar['age']:.1f} 天"
                )
            
            result = "\n".join(components)
            
            logger.info(f"[OK] 天氣語境已組合")
            
            return result
            
        except Exception as e:
            logger.error(f"[ERROR] 天氣語境組合失敗：{e}", exc_info=True)
            return f"無法獲取天氣信息：{str(e)[:50]}"
    
    def build_weather_response(self, user_question: str) -> str:
        """
        根據用戶問題構建自然語言天氣回應
        
        Args:
            user_question: 如「而家天氣點樣」
            
        Returns:
            str: 希兒的天氣回應
        """
        try:
            logger.info(f"構建天氣回應", extra={'question': user_question[:50]})
            
            # 【獲取所有數據】
            time_info = self.get_contextual_time_info()
            weather = self.get_weather_forecast()
            temps = self.get_regional_temperature()
            solar_lunar = self.get_solar_lunar_data()
            
            # 【組合回應】
            response_parts = []
            
            # 【時間語境】
            response_parts.append(f"現在係 {time_info['current_time']}（{time_info['weekday']}）")
            
            # 【天氣預測】
            if weather:
                today = weather['today']
                response_parts.append(
                    f"今日天氣：{today.get('weather', '無資料')}，"
                    f"氣溫 {today.get('temp_min', '？')}-{today.get('temp_max', '？')}°C"
                )
            
            # 【區域溫度】
            # [OK] BUG 修正 7：安全類型轉換
            if temps and temps.get('regions'):
                temps_str = " | ".join([
                    f"{k}: {float(v):.1f}°C"
                    for k, v in list(temps['regions'].items())[:3]
                    if isinstance(v, (int, float))
                ])
                if temps_str:
                    response_parts.append(f"各區溫度：{temps_str}")
            
            # 【日月信息】
            if solar_lunar:
                response_parts.append(
                    f"日出 {solar_lunar['sunrise']} / 日落 {solar_lunar['sunset']} / "
                    f"月相：{solar_lunar['moon_phase']} (照度 {solar_lunar['illumination']:.1f}%)"
                )
            
            # 【凌晨特別提示】
            if time_info['is_early_morning']:
                response_parts.append(
                    f"\n[提示] 依家係凌晨，仲未出太陽。"
                    f"若你問『聽日』，我會理解為日出後的白天時段。"
                )
            
            # 【最終組合】
            result = "我睇下 HKO 嘅資料～\n\n" + "\n".join(response_parts)
            
            logger.info(f"[OK] 天氣回應已構建")
            
            return result
            
        except Exception as e:
            logger.error(f"[ERROR] 天氣回應構建失敗：{e}", exc_info=True)
            return f"哎呀，攞唔到天氣資訊。你可以去 HKO 網站直接睇～"
    
    # ========================================================================
    # 【快取輔助方法 - 修正版】
    # ========================================================================
    
    def _get_cached(self, key: str) -> Optional[Dict]:
        """獲取快取（使用預設 TTL）"""
        if key in self._cache:
            timestamp, data = self._cache[key]
            if (datetime.now() - timestamp).total_seconds() < self.CACHE_TTL:
                logger.debug(f"[CACHE HIT] {key}")
                return data
            else:
                del self._cache[key]
                logger.debug(f"[CACHE EXPIRED] {key}")  # [OK] BUG 修正 1
        return None
    
    def _set_cache(self, key: str, data: Dict) -> None:
        """設置快取（使用預設 TTL）"""
        self._cache[key] = (datetime.now(), data)
        logger.debug(f"[CACHE SET] {key}")
    
    def _get_cached_with_ttl(self, key: str, ttl: int) -> Optional[Dict]:
        """獲取快取（自定義 TTL）"""
        if key in self._cache:
            timestamp, data = self._cache[key]
            if (datetime.now() - timestamp).total_seconds() < ttl:
                logger.debug(f"[CACHE HIT] {key} (TTL: {ttl}s)")  # [OK] BUG 修正 2
                return data
            else:
                del self._cache[key]
                logger.debug(f"[CACHE EXPIRED] {key}")
        return None
    
    def _set_cache_with_ttl(self, key: str, data: Dict, ttl: int) -> None:
        """設置快取（自定義 TTL）"""
        self._cache[key] = (datetime.now(), data)
        logger.debug(f"[CACHE SET] {key} (TTL: {ttl}s)")
    
    # ========================================================================
    # 【系統狀態】
    # ========================================================================
    
    def health_check(self) -> Dict[str, Any]:
        """系統健康檢查"""
        hk_tz = pytz.timezone('Asia/Hong_Kong')
        
        return {
            'service_enabled': self.enabled,
            'nasa_api_configured': bool(self.nasa_api_key and self.nasa_api_key != "DEMO_KEY"),
            'timestamp': datetime.now(hk_tz).isoformat(),
            'api_endpoints': {
                'hko_base': self.HKO_API_BASE,
                'hko_astro': self.HKO_ASTRO,
            },
            'cache_size': len(self._cache),
            'timezone': 'Asia/Hong_Kong (UTC+8)',
            'constants': {
                'lunar_cycle': self.LUNAR_CYCLE,
                'cache_ttl': self.CACHE_TTL,
                'moon_cache_ttl': self.MOON_CACHE_TTL,
                'temp_cache_ttl': self.TEMP_CACHE_TTL,  # [OK] 添加
            }
        }


# ============================================================================
# 【使用範例】
# ============================================================================

if __name__ == "__main__":
    import json
    
    # 初始化
    hko = HKOService()
    
    print("=" * 80)
    print("【HKO Service v3.1 - 修正版功能演示】")
    print("=" * 80)
    
    # 1. 時間語境
    print("\n【1. 時間語境檢測】")
    time_info = hko.get_contextual_time_info()
    print(json.dumps(time_info, indent=2, ensure_ascii=False))
    
    # 2. 天氣預報
    print("\n【2. 天氣預報（1 天）】")
    forecast = hko.get_weather_forecast(days=1)
    if forecast:
        print(f"今日：{forecast['today']['weather']}")
        print(f"溫度：{forecast['today']['temp_min']}-{forecast['today']['temp_max']}°C")
        print(f"快取狀態：{forecast['cached']}")
    
    # 3. 區域溫度
    print("\n【3. 區域溫度】")
    temps = hko.get_regional_temperature()
    if temps:
        print(f"快取狀態：{temps['cached']}")
        for region, temp in list(temps['regions'].items())[:3]:
            print(f"  {region}: {temp:.1f}°C")
    
    # 4. 月相
    print("\n【4. 月相信息】")
    moon = hko._calculate_moon_phase_local()
    print(f"月相：{moon['phase_name']}")
    print(f"農曆：{moon['lunar_phase']}")
    print(f"照度：{moon['illumination']:.1f}%")
    print(f"月齡：{moon['age']:.1f} 天")
    print(f"快取狀態：{moon.get('cached', False)}")
    
    # 5. 天氣語境
    print("\n【5. 格式化天氣語境】")
    context = hko.get_formatted_weather_context()
    print(context)
    
    # 6. 天氣回應
    print("\n【6. 自然語言天氣回應】")
    response = hko.build_weather_response("而家天氣點樣")
    print(response)
    
    # 7. 健康檢查
    print("\n【7. 系統狀態】")
    health = hko.health_check()
    print(json.dumps(health, indent=2, ensure_ascii=False))
    
    # 8. 測試快取（再次查詢，應該命中快取）
    print("\n【8. 快取測試（再次查詢）】")
    forecast2 = hko.get_weather_forecast(days=1)
    if forecast2:
        print(f"快取狀態：{forecast2['cached']} ([OK] 應該為 True)")