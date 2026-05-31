import asyncio
import os
os.environ['PYTHONIOENCODING'] = 'utf-8'

from nl2dsl.config import settings
from nl2dsl.agent.planner import Planner
from nl2dsl.llm.client import LLMClient

async def main():
    print(f'API key exists: {bool(settings.llm_api_key)}')
    print(f'Model: {settings.llm_model}')
    print()

    # Create planner with real LLM
    if settings.llm_api_key:
        llm = LLMClient(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )
        planner = Planner(llm_client=llm)
    else:
        planner = Planner()
        llm = None

    for q in ['各品类销售额占比', '销售额排名前5', '先查华东再查华南']:
        print(f'Query: {q}')

        # Check rule-based first
        rule_plan = planner._rule_based_plan(q)
        print(f'  rule-based intent: {rule_plan.intent}')

        # Check LLM plan
        if llm:
            try:
                llm_plan = await planner._llm_plan(q, {})
                print(f'  LLM intent: {llm_plan.intent}')

                if llm_plan.intent == 'single_query' and rule_plan.intent != 'single_query':
                    print(f'  -> OVERRIDDEN to: {rule_plan.intent}')
                else:
                    print(f'  -> Using LLM: {llm_plan.intent}')
            except Exception as e:
                print(f'  LLM error: {e}')
                print(f'  -> Fallback to: {rule_plan.intent}')
        else:
            print(f'  No LLM, using rule-based: {rule_plan.intent}')

        # Final plan
        final_plan = await planner.plan(q)
        print(f'  FINAL intent: {final_plan.intent}')
        print()

asyncio.run(main())
