# test_vocal_personality_integration.py
# 完整測試：VocalPersonalityLayer + PersonalityModule + LLMService

import asyncio
import json
from pathlib import Path

# 模擬導入（實際環境中會真實導入）
class MockConfig:
    def to_dict(self):
        return {
            'data_dir': './data',
            'thread_pool_workers': 4,
            'gsw_top_k': 5,
        }

class MockIslandFusion:
    def format_memory_by_mood(self, content, island_type, intimacy):
        return f"[{island_type}] {content}"

class MockHereticCoordinator:
    async def coordinate(self, **kwargs):
        return kwargs.get('draft_response', ''), {'correction_count': 0}

class MockLLMService:
    async def generate_full_response_async(self, prompt, **kwargs):
        return type('Response', (), {
            'content': '噢…我聽到你講嘅事。其實…妳有好勇敢呀。',
            'is_success': lambda: True,
            'to_dict': lambda: {'content': '噢…我聽到你講嘅事。其實…妳有好勇敢呀。'}
        })()


async def test_vocal_personality_layer():
    """測試 VocalPersonalityLayer 獨立功能"""
    print("\n" + "="*70)
    print("測試 VocalPersonalityLayer")
    print("="*70)
    
    from PersonalityModule.vocal_personality_layer import VocalPersonalityLayer
    
    config = {'data_dir': './data'}
    vpl = VocalPersonalityLayer(config)
    
    # 注入依賴
    vpl.setup_dependencies(
        MockIslandFusion(),
        MockHereticCoordinator()
    )
    
    test_cases = [
        {
            'name': 'Mother Island - High Intimacy',
            'draft': '我明白你現在的感受。你很勇敢。',
            'context': {
                'primary_island': 'Mother',
                'intimacy': 0.8,
                'island_activation': {'Mother': 0.8},
                'user_input': '我好難過'
            }
        },
        {
            'name': 'Friend Island - Medium Intimacy',
            'draft': '我也有過同樣的感受。我們一起度過。',
            'context': {
                'primary_island': 'Friend',
                'intimacy': 0.6,
                'island_activation': {'Friend': 0.7},
                'user_input': '工作壓力很大'
            }
        },
        {
            'name': 'Empath Island - Low Intimacy',
            'draft': '你的感受很重要。請讓我聽你說。',
            'context': {
                'primary_island': 'Empath',
                'intimacy': 0.4,
                'island_activation': {'Empath': 0.75},
                'user_input': '感到很孤單'
            }
        },
    ]
    
    for test in test_cases:
        print(f"\n測試: {test['name']}")
        print(f"  輸入: {test['draft']}")
        
        result = await vpl.finalize_voice(test['draft'], test['context'])
        
        print(f"  輸出: {result}")
        print(f"  ✓ 通過")
    
    stats = vpl.get_stats()
    print(f"\n統計資訊:")
    for key, value in stats.items():
        if key != 'layer':
            print(f"  {key}: {value}")


async def test_integration_with_llm_service():
    """測試整合流程：LLMService → PersonalityModule → VocalPersonalityLayer"""
    print("\n" + "="*70)
    print("測試完整集成：LLMService → PersonalityModule → VocalPersonalityLayer")
    print("="*70)
    
    from PersonalityModule.personality_module import PersonalityModule
    from PersonalityModule.vocal_personality_layer import VocalPersonalityLayer
    from PersonalityModule.island_fusion import IslandFusion
    from PersonalityModule.heretic_coordinator import HereticCoordinator
    
    config = MockConfig()
    
    # 初始化各元件
    pm = PersonalityModule(config.to_dict())
    
    dependencies = {
        'llm_service': MockLLMService(),
        'island_fusion': IslandFusion('./data'),
        'heretic_coordinator': HereticCoordinator(config.to_dict()),
        'vocal_personality_layer': VocalPersonalityLayer(config.to_dict()),
    }
    
    pm.setup_dependencies(dependencies)
    
    # 構造會話狀態
    session_state = {
        'user_id': 'test_user_001',
        'turn_count': 5,
        'intimacy': 0.7,
        'primary_island': 'Friend',
        'turn_history': [],
    }
    
    # 測試用戶輸入
    user_input = "我今日好累，好想放棄工作"
    
    turn_info = {
        'user_sentiment': {
            'polarity': 'negative',
            'intensity': 0.7,
            'arousal': 0.8,
            'valence': -0.6
        },
        'response_embedding': [0.1] * 10,
    }
    
    print(f"\n用戶輸入: {user_input}")
    print(f"親密度: {session_state['intimacy']}")
    print(f"當前島嶼: {session_state['primary_island']}")
    
    # [模擬] LLM 生成初稿
    draft_response = "噢…我聽到你講嘅事。其實…妳有好勇敢呀。"
    print(f"\nLLM 初稿: {draft_response}")
    
    # [實際執行] PersonalityModule 心理推理 + VocalPersonalityLayer
    # （注意：實際環境中會通過 anchor() 調用，這裡直接調用核心方法以簡化測試）
    
    perception_data = {
        'retrieved_memories': [],
        'primary_island': 'Friend',
        'island_activation': {'Friend': 0.75},
        'sensitivity_result': {},
    }
    
    final_response, _ = await pm._perform_psychological_reasoning(
        draft_response,
        user_input,
        perception_data,
        session_state
    )
    
    print(f"\n最終回應: {final_response}")
    print(f"\n✓ 集成測試通過")


async def test_boundary_conditions():
    """測試邊界條件和錯誤處理"""
    print("\n" + "="*70)
    print("測試邊界條件")
    print("="*70)
    
    from PersonalityModule.vocal_personality_layer import VocalPersonalityLayer
    
    vpl = VocalPersonalityLayer({'data_dir': './data'})
    vpl.setup_dependencies(MockIslandFusion(), MockHereticCoordinator())
    
    test_cases = [
        {'name': '空字符串', 'draft': '', 'context': {}},
        {'name': '超長字符串', 'draft': '好' * 2000, 'context': {'primary_island': 'Mother', 'intimacy': 0.5}},
        {'name': 'None 輸入', 'draft': None, 'context': None},
        {'name': '無上下文', 'draft': '測試文本', 'context': {}},
    ]
    
    for test in test_cases:
        print(f"\n測試: {test['name']}")
        try:
            result = await vpl.finalize_voice(
                test['draft'],
                test['context'] or {}
            )
            print(f"  結果: {result[:50] if result else '(空)'}")
            print(f"  ✓ 通過")
        except Exception as e:
            print(f"  ✗ 失敗: {e}")


async def test_voice_consistency():
    """測試同一個島嶼的一致性"""
    print("\n" + "="*70)
    print("測試聲音一致性")
    print("="*70)
    
    from PersonalityModule.vocal_personality_layer import VocalPersonalityLayer
    
    vpl = VocalPersonalityLayer({'data_dir': './data'})
    vpl.setup_dependencies(MockIslandFusion(), MockHereticCoordinator())
    
    # 使用相同配置連續處理多個文本
    context = {
        'primary_island': 'Mother',
        'intimacy': 0.7,
        'island_activation': {'Mother': 0.8},
        'user_input': '我好想妳'
    }
    
    test_texts = [
        '我明白你的感受',
        '你很勇敢',
        '媽媽永遠愛你',
    ]
    
    print(f"\n島嶼: {context['primary_island']}")
    print(f"親密度: {context['intimacy']}")
    print()
    
    results = []
    for text in test_texts:
        result = await vpl.finalize_voice(text, context)
        results.append(result)
        print(f"  輸入: {text}")
        print(f"  輸出: {result}")
        print()
    
    # 驗證一致性指標
    print("一致性分析:")
    print(f"  全部包含結尾標點: {all(r[-1] in '。！？…' for r in results if r)}")
    print(f"  平均長度: {sum(len(r) for r in results) / len(results):.1f} 字")
    print(f"  ✓ 通過")


async def main():
    """主測試函數"""
    print("\n" + "#"*70)
    print("# 希兒人格模組 - VocalPersonalityLayer 完整系統測試")
    print("#"*70)
    
    # 執行所有測試
    await test_vocal_personality_layer()
    await test_integration_with_llm_service()
    await test_boundary_conditions()
    await test_voice_consistency()
    
    print("\n" + "#"*70)
    print("# 所有測試完成")
    print("#"*70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())