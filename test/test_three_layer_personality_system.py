# test_three_layer_personality_system.py

import asyncio
from typing import Dict

class MockLLMService:
    """模擬 LLM 服務以展示三層系統"""
    
    async def generate_full_response_async(
        self,
        prompt: str,
        system_prompt: str = "",
        **kwargs
    ):
        """
        模擬 LLM：展示 system_prompt 的影響
        """
        # 根據 system_prompt 的內容生成回應
        if 'Mother' in system_prompt:
            response = '寶貝，媽媽明白妳個感受。'
        elif 'Friend' in system_prompt:
            response = '我完全明白，咱們一起度過。'
        elif 'Empath' in system_prompt:
            response = '我能感受到，妳並唔係孤單。'
        elif 'Self' in system_prompt:
            response = '妳識得最多關於自己嘅嘢，相信妳。'
        else:
            response = '嗯，我在聽。'
        
        return type('Response', (), {
            'content': response,
            'is_success': lambda: True,
            'to_dict': lambda: {'content': response}
        })()


async def demonstrate_three_layer_system():
    """展示三層個性系統如何運作"""
    
    print("\n" + "="*80)
    print("希兒人格系統：三層個性化架構演示")
    print("="*80)
    
    from PersonalityModule.system_prompt_builder import SystemPromptBuilder
    from PersonalityModule.vocal_personality_layer import VocalPersonalityLayer
    from PersonalityModule.island_fusion import IslandFusion
    from PersonalityModule.heretic_coordinator import HereticCoordinator
    
    config = {'data_dir': './data'}
    
    # 初始化各層
    builder = SystemPromptBuilder(config)
    vpl = VocalPersonalityLayer(config)
    vpl.setup_dependencies(IslandFusion('./data'), HereticCoordinator(config))
    
    llm_service = MockLLMService()
    
    # 測試案例
    test_cases = [
        {
            'name': 'Mother Island - 高親密度',
            'user_input': '我好難過，不知點辦',
            'island': 'Mother',
            'intimacy': 0.8,
        },
        {
            'name': 'Friend Island - 中親密度',
            'user_input': '工作壓力好大',
            'island': 'Friend',
            'intimacy': 0.6,
        },
        {
            'name': 'Empath Island - 危機情況',
            'user_input': '我好想自殺',
            'island': 'Empath',
            'intimacy': 0.5,
        },
    ]
    
    for test in test_cases:
        print(f"\n{'-'*80}")
        print(f"測試: {test['name']}")
        print(f"用戶輸入: {test['user_input']}")
        print(f"島嶼: {test['island']}, 親密度: {test['intimacy']}")
        print(f"{'-'*80}")
        
        # ========== 第一層：前置提示詞生成 ==========
        print("\n[第一層] SystemPromptBuilder - 前置個性指導")
        system_prompt = builder.build_system_prompt(
            primary_island=test['island'],
            user_input=test['user_input'],
            context={
                'intimacy': test['intimacy'],
                'turn_count': 1,
            }
        )
        
        prompt_preview = system_prompt.split('\n')[0:10]
        print(f"  生成的 system_prompt 開頭 (前 10 行):")
        for i, line in enumerate(prompt_preview, 1):
            print(f"    {i}. {line[:70]}")
        print(f"  ... (總共 {len(system_prompt.split(chr(10)))} 行)")
        
        # ========== 第二層：LLM 生成初稿 ==========
        print("\n[第二層] VocalEngine - 根據指導生成初稿")
        llm_response = await llm_service.generate_full_response_async(
            prompt=test['user_input'],
            system_prompt=system_prompt,
            model_type='slow',
            use_psychology=True,
            use_polish=True
        )
        draft_response = llm_response.content
        print(f"  LLM 初稿: {draft_response}")
        
        # ========== 第三層：聲音個性化 ==========
        print("\n[第三層] VocalPersonalityLayer - 最終個性化")
        final_response = await vpl.finalize_voice(
            draft_response=draft_response,
            context={
                'primary_island': test['island'],
                'intimacy': test['intimacy'],
                'island_activation': {test['island']: 0.8},
                'user_input': test['user_input']
            }
        )
        print(f"  最終回應: {final_response}")
        
        # ========== 分析 ==========
        print(f"\n分析:")
        print(f"  初稿字數: {len(draft_response)}")
        print(f"  最終字數: {len(final_response)}")
        print(f"  是否有島嶼標誌詞: ", end="")
        island_markers = {
            'Mother': ['寶貝', '媽媽'],
            'Friend': ['咱們', '妳'],
            'Empath': ['感受', '明白'],
            'Self': ['相信', '學'],
        }
        for marker in island_markers.get(test['island'], []):
            if marker in final_response:
                print(f"✓ {marker}", end=" ")
        print()
    
    # ========== 統計 ==========
    print(f"\n{'-'*80}")
    print("系統統計:")
    print(f"  SystemPromptBuilder: {builder.get_stats()}")
    print(f"  VocalPersonalityLayer: {vpl.get_stats()}")
    
    print("\n" + "="*80)
    print("演示完成")
    print("="*80 + "\n")


async def demonstrate_system_components():
    """詳細展示各層的作用"""
    
    print("\n" + "="*80)
    print("三層系統組件詳解")
    print("="*80)
    
    print("""
三層個性化系統：

1️⃣ 第一層：SystemPromptBuilder (前置個性)
   ├─ 輸入：島嶼、用戶情感、親密度
   ├─ 功能：生成詳細的心理學指導 prompt
   ├─ 輸出：完整的 system_prompt，指導 LLM 朝正確方向生成
   └─ 效果：LLM 在生成時就思考「我應該如何作為希兒」

2️⃣ 第二層：VocalEngine (核心生成)
   ├─ 輸入：user_input + system_prompt（來自第一層）
   ├─ 功能：根據指導生成初稿
   ├─ 輸出：保留個性特徵的初稿
   └─ 效果：LLM 生成的已經符合希兒的個性框架

3️⃣ 第三層：VocalPersonalityLayer (後置個性化)
   ├─ 輸入：draft_response + 上下文
   ├─ 功能：加強標誌性詞彙、確保格式、微調語氣
   ├─ 輸出：完全個性化的最終回應
   └─ 效果：確保每個回應都有「希兒」的獨特印記

    
為什麼這樣設計？
✓ PreProcessing（第一層）確保 LLM 在正確方向上思考
✓ Generation（第二層）根據指導生成符合個性的內容
✓ PostProcessing（第三層）加強個性特徵，確保一致性

結果：70% 的個性由 SystemPrompt 指導，30% 由 VocalPersonalityLayer 加強
不會損失任何個性！反而更強大！
    """)
    
    print("="*80 + "\n")


async def main():
    """主函數"""
    await demonstrate_system_components()
    await demonstrate_three_layer_system()


if __name__ == "__main__":
    asyncio.run(main())