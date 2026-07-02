# PersonalityModule/cantonese_dict.py
# 希兒粵語詞典模組 v3.0 - 基於 rime-cantonese 詞庫（效能優化版）

import pandas as pd
from pathlib import Path
import logging
import os
import sys
from typing import Dict, List, Optional

logger = logging.getLogger('cantonese_dict')
logger.setLevel(logging.DEBUG)

# ==================== 路徑配置（含REPL防護） ====================

if '__file__' in globals():
    BASE_DIR = Path(__file__).parent.parent
    logger.debug("[INFO] 使用檔案位置計算 BASE_DIR")
else:
    BASE_DIR = Path(os.getcwd()).parent
    logger.warning("[WARN] 使用當前工作目錄計算 BASE_DIR（REPL環境檢測）")

DICT_PATH = BASE_DIR / "dict"
FALLBACK_DICT_PATH = Path("D:/Desktop/engine7b/dict")

if not DICT_PATH.exists():
    logger.warning(f"[WARN] 相對路徑不存在: {DICT_PATH}")
    if FALLBACK_DICT_PATH.exists():
        DICT_PATH = FALLBACK_DICT_PATH
        logger.info(f"[FALLBACK] 切換到絕對路徑: {DICT_PATH}")
    else:
        logger.error(f"[CRITICAL] 兩個路徑均不存在！相對: {BASE_DIR / 'dict'}，絕對: {FALLBACK_DICT_PATH}")

logger.info(f"[INFO] 字典載入路徑: {DICT_PATH}")

# ==================== 直接讀取 rime-cantonese yaml 詞庫 ====================

RIME_DF = pd.DataFrame(columns=['word', 'jyutping'])
RIME_DICT = {}  # [效能優化] O(1) 查詞字典

rime_files = [
    'jyut6ping3.chars.dict.yaml',
    'jyut6ping3.words.dict.yaml',
    'jyut6ping3.phrase.dict.yaml',
    'jyut6ping3.lettered.dict.yaml',
]

all_lines = []
total_before_dedupe = 0

for fname in rime_files:
    fpath = DICT_PATH / 'rime-cantonese-main' / fname
    
    if not fpath.exists():
        logger.warning(f"[SKIP] rime 檔案不存在: {fpath}")
        continue
    
    logger.info(f"[LOADING] 讀取 rime 詞庫: {fname}")
    count = 0
    
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                if (not line or 
                    line.startswith('#') or 
                    line.startswith('---') or 
                    line.startswith('...') or
                    line.startswith('name:') or
                    line.startswith('version:') or
                    line.startswith('sort:') or
                    line.startswith('use_preset_vocabulary:') or
                    line.startswith('columns:')):
                    continue
                
                if '\t' not in line:
                    continue
                
                parts = line.split('\t')
                if len(parts) < 2:
                    logger.debug(f"[WARN] {fname}:{line_num} 欄位不足 (只有{len(parts)}個): {line[:50]}")
                    continue
                
                word = parts[0].strip()
                jyutping = parts[1].strip()
                
                if word and jyutping:
                    all_lines.append({'word': word, 'jyutping': jyutping})
                    count += 1
                else:
                    logger.debug(f"[WARN] {fname}:{line_num} 詞或讀音為空: word='{word}' jyutping='{jyutping}'")
    
    except Exception as e:
        logger.error(f"[ERROR] 讀取 {fname} 失敗: {e}", exc_info=True)
        continue
    
    logger.info(f"[OK] 從 {fname} 載入 {count} 條詞")
    total_before_dedupe += count

if all_lines:
    RIME_DF = pd.DataFrame(all_lines)
    
    initial_count = len(RIME_DF)
    RIME_DF = RIME_DF.drop_duplicates(subset=['word'], keep='first')
    dedupe_count = initial_count - len(RIME_DF)
    
    logger.info(f"[DEDUPE] 去重完成: {initial_count} → {len(RIME_DF)} 條（移除{dedupe_count}條重複）")
    
    # [效能優化] 建立 O(1) 查詞字典
    RIME_DICT = dict(zip(RIME_DF['word'], RIME_DF['jyutping']))
    logger.info(f"[PERF] 快速查詞字典構建完成，共 {len(RIME_DICT)} 條")
    logger.info(f"[FINAL] rime 合併完成，共 {len(RIME_DF)} 條唯一詞彙（原始{total_before_dedupe}條）")
else:
    logger.error("[CRITICAL] 所有 rime yaml 都沒載入成功，RIME_DF 為空！")

# ==================== 載入詞性表 ====================

POS_DF = pd.DataFrame()
POS_DICT = {}  # [效能優化] O(1) 查詞性

try:
    pos_path = DICT_PATH / "words_hk_pos.csv"
    if pos_path.exists():
        POS_DF = pd.read_csv(
            pos_path,
            low_memory=False,
            on_bad_lines='skip',
            header=None,
            encoding='utf-8'
        )
        if POS_DF.shape[1] >= 2:
            POS_DF = POS_DF.iloc[:, :2].copy()
            POS_DF.columns = ['word', 'pos']
            POS_DF = POS_DF.reset_index(drop=True)
            
            # [效能優化] 建立詞性字典
            POS_DICT = dict(zip(POS_DF['word'], POS_DF['pos']))
            logger.info(f"[PERF] 詞性查詞字典構建完成，共 {len(POS_DICT)} 條")
        
        logger.info(f"[OK] 詞性表載入完成，共 {len(POS_DF)} 條")
    else:
        logger.warning(f"[WARN] 詞性表不存在: {pos_path}")
except Exception as e:
    logger.error(f"[ERROR] 載入 words_hk_pos.csv 失敗: {e}", exc_info=True)

# ==================== 載入成語表 ====================

IDIOMS_DF = pd.DataFrame()
try:
    idiom_path = DICT_PATH / "hk_idioms.xlsx"
    if idiom_path.exists():
        IDIOMS_DF = pd.read_excel(idiom_path)
        logger.info(f"[OK] 成語表載入完成，共 {len(IDIOMS_DF)} 條")
    else:
        logger.warning(f"[WARN] 成語表不存在: {idiom_path}")
except Exception as e:
    logger.error(f"[ERROR] 載入 hk_idioms.xlsx 失敗: {e}", exc_info=True)

# ==================== 載入 yyzd 字音字典（罕用字補充） ====================

YYZD_DICT = {}
try:
    yyzd_path = DICT_PATH / "yyzd.txt"
    if yyzd_path.exists():
        with open(yyzd_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                parts = line.strip().split("\t")
                
                if len(parts) >= 2:
                    char = parts[0].strip()
                    jyutping = parts[1].strip()
                    
                    if char and jyutping:
                        YYZD_DICT[char] = {"jyutping": jyutping}
                    else:
                        logger.debug(f"[WARN] yyzd.txt:{line_num} 字或讀音為空")
                else:
                    logger.debug(f"[WARN] yyzd.txt:{line_num} 欄位不足: {line.strip()[:50]}")
        
        logger.info(f"[OK] yyzd 字音字典載入完成，共 {len(YYZD_DICT)} 字")
    else:
        logger.warning(f"[WARN] yyzd.txt 不存在: {yyzd_path}")
except Exception as e:
    logger.error(f"[ERROR] 載入 yyzd.txt 失敗: {e}", exc_info=True)

# ==================== 查詢函數 ====================

def search_word(word: str) -> dict:
    """
    查詢單個詞語的資訊（優先級：rime > yyzd fallback > 詞性表）
    [效能優化] O(1) 時間複雜度
    
    Args:
        word (str): 粵語詞語
    
    Returns:
        dict: {
            'word': 原始查詢詞,
            'found': 是否找到,
            'jyutping': 粵音（若找到）,
            'pos': 詞性（若有詞性表匹配）,
            'source': 資料來源（'rime-cantonese' 或 'yyzd'）
        }
    """
    result = {"word": word, "found": False}
    
    # [優先級1] RIME 字典 (Hash Map O(1) 查詢)
    if word in RIME_DICT:
        result["found"] = True
        result["jyutping"] = RIME_DICT[word]
        result["source"] = "rime-cantonese"
    
    # [優先級2] 詞性表補充 (O(1) 查詞性字典)
    if word in POS_DICT:
        result["pos"] = str(POS_DICT[word])
    
    # [優先級3] yyzd 字音補充（只限單字且未在 rime 中找到）
    if (not result.get("jyutping") and 
        len(word) == 1 and 
        word in YYZD_DICT):
        result["found"] = True
        result["jyutping"] = YYZD_DICT[word]["jyutping"]
        result["source"] = "yyzd"
    
    return result


def search_idiom(keyword: str) -> list:
    """
    查詢成語
    
    Args:
        keyword (str): 成語關鍵字
    
    Returns:
        list: 符合的成語列表（最多5條）
    """
    if IDIOMS_DF.empty:
        logger.warning("[WARN] 成語表為空")
        return []
    
    idiom_col = None
    
    if '成語' in IDIOMS_DF.columns:
        idiom_col = '成語'
    elif 'idiom' in IDIOMS_DF.columns:
        idiom_col = 'idiom'
    elif len(IDIOMS_DF.columns) > 1:
        idiom_col = IDIOMS_DF.columns[1]
    else:
        idiom_col = IDIOMS_DF.columns[0]
    
    logger.debug(f"[DEBUG] 成語搜尋欄位: {idiom_col}")
    
    try:
        matches = IDIOMS_DF[
            IDIOMS_DF[idiom_col].astype(str).str.contains(keyword, na=False, regex=False)
        ]
        results = matches.head(5).to_dict('records')
        logger.info(f"[OK] 成語查詢成功: '{keyword}' 找到 {len(results)} 條")
        return results
    except Exception as e:
        logger.error(f"[ERROR] 成語搜尋失敗: {e}", exc_info=True)
        return []


def search_phrase(phrase: str, max_results: int = 5) -> list:
    """
    搜尋短語（支援模糊匹配）
    注意：此方法仍需使用 DataFrame 進行 str.contains
    
    Args:
        phrase (str): 搜尋短語
        max_results (int): 最大結果數
    
    Returns:
        list: 匹配的詞彙列表
    """
    if RIME_DF.empty:
        return []
    
    try:
        matches = RIME_DF[
            RIME_DF['word'].str.contains(phrase, na=False, regex=False)
        ]
        results = matches.head(max_results).to_dict('records')
        logger.info(f"[OK] 短語搜尋: '{phrase}' 找到 {len(results)} 條")
        return results
    except Exception as e:
        logger.error(f"[ERROR] 短語搜尋失敗: {e}", exc_info=True)
        return []


def get_dict_stats() -> dict:
    """
    取得字典統計資訊（用於除錯和狀態檢查）
    
    Returns:
        dict: 各字典的加載狀態與數量
    """
    return {
        "rime_cantonese": len(RIME_DICT),
        "pos_table": len(POS_DICT),
        "idioms": len(IDIOMS_DF) if not IDIOMS_DF.empty else 0,
        "yyzd": len(YYZD_DICT),
        "dict_path": str(DICT_PATH),
        "environment": "REPL" if '__file__' not in globals() else "File"
    }


def batch_search(words: list) -> list:
    """
    批量查詢詞語（效率更高，O(n) 批量查詞）
    
    Args:
        words (list): 詞語列表
    
    Returns:
        list: 查詢結果列表
    """
    return [search_word(w) for w in words]

# ==================== 測試區塊 ====================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("希兒粵語詞典模組 v3.0 - 自測程式（效能優化版）")
    print("="*70 + "\n")
    
    stats = get_dict_stats()
    print("[字典加載狀態]")
    print(f"  環境: {stats['environment']}")
    print(f"  rime-cantonese: {stats['rime_cantonese']:,} 條詞")
    print(f"  詞性表: {stats['pos_table']:,} 條")
    print(f"  成語表: {stats['idioms']:,} 條")
    print(f"  yyzd字音: {stats['yyzd']:,} 字")
    print(f"  路徑: {stats['dict_path']}\n")
    
    print("[詞語查詢測試]")
    test_words = ["溫柔", "陪伴", "愛", "希", "龍", "鳳凰", "人工智能"]
    
    for test_word in test_words:
        result = search_word(test_word)
        status = "✓ 找到" if result["found"] else "✗ 未找到"
        source = f"({result.get('source', 'N/A')})" if result["found"] else ""
        jyutping = f" → {result.get('jyutping', '')}" if result["found"] else ""
        print(f"  {status} - '{test_word}': {source}{jyutping}")
    
    print()
    print("[成語查詢測試]")
    test_keywords = ["龍", "鳳", "心"]
    for keyword in test_keywords:
        results = search_idiom(keyword)
        print(f"  關鍵字 '{keyword}': 找到 {len(results)} 條成語")
        if results:
            for i, idiom in enumerate(results[:2], 1):
                idiom_str = str(idiom).replace('{', '').replace('}', '')[:50]
                print(f"    {i}. {idiom_str}")
    
    print()
    print("[短語搜尋測試]")
    test_phrases = ["人工", "智能", "機器"]
    for phrase in test_phrases:
        results = search_phrase(phrase, max_results=3)
        print(f"  短語 '{phrase}': 找到 {len(results)} 條")
        if results:
            for i, item in enumerate(results[:3], 1):
                print(f"    {i}. {item['word']} [{item['jyutping']}]")
    
    print()
    print("[批量查詢測試]")
    batch_words = ["希兒", "粵語", "詞典"]
    batch_results = batch_search(batch_words)
    for result in batch_results:
        status = "✓" if result["found"] else "✗"
        print(f"  {status} {result['word']}: {result.get('jyutping', 'N/A')}")
    
    print("\n" + "="*70)
    print("自測完成 ✓")
    print("="*70 + "\n")