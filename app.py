import streamlit as st
import json
import csv
import os
import datetime
from openai import OpenAI

st.title("剩菜拯救者 Demo")
st.caption("库存驱动 + 家常菜生成器")

# --- 侧边栏：兼容云端 Secrets 和本地输入 ---
with st.sidebar:
    st.header("配置")
    try:
        # 尝试读取云端 Secrets
        api_key = st.secrets["OPENAI_API_KEY"]
        st.success("API Key 已自动加载")
    except Exception:
        # 本地没有 Secrets 文件，平滑降级为手动输入
        api_key = st.text_input("API Key", type="password", help="输入 DeepSeek 或兼容 OpenAI 格式的 Key")

    model_name = st.text_input("模型", value="deepseek-chat")
    base_url = st.text_input("Base URL", value="https://api.deepseek.com")

st.subheader("1. 输入现有食材")
ingredients = st.text_area(
    "食材列表（最多10种）",
    placeholder="例如：半个土豆、一根火腿肠、两个鸡蛋、半个洋葱",
    height=100
)

st.subheader("2. 设置硬约束")
preset_cookware = ["电煮锅", "微波炉", "平底锅", "烤箱", "空气炸锅", "电饭煲"]
selected_cookware = st.multiselect("可用厨具（至少选1个）", preset_cookware)
custom_cookware = st.text_input("自定义厨具（可选，多个用逗号分隔）", placeholder="例如：电饼铛, 蒸锅")
custom_cookware_list = [c.strip() for c in custom_cookware.split(",") if c.strip()] if custom_cookware else []
cookware = selected_cookware + custom_cookware_list

time_option = st.radio("最长烹饪时间", ["10分钟", "20分钟", "30分钟", "自定义"], horizontal=True)
if time_option == "自定义":
    max_time = st.number_input("自定义分钟数", min_value=1, max_value=120, value=15, step=1)
else:
    max_time = int(time_option.replace("分钟", ""))

dietary = st.text_input("忌口 / 过敏（可留空）", placeholder="例如：不要辣、不吃香菜")

st.divider()


# --- 反馈落盘函数 ---
def save_feedback(recipe_name, feasible):
    file_exists = os.path.isfile("feedback.csv")
    with open("feedback.csv", "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "recipe_name", "feasible"])
        writer.writerow([datetime.datetime.now().isoformat(), recipe_name, feasible])


# --- 渲染卡片函数 ---
def render_recipes(recipes):
    cols = st.columns(3)
    for i, col in enumerate(cols):
        with col:
            recipe = recipes[i]
            st.subheader(recipe["name"])
            st.caption(f"耗时: {recipe['time']}分钟 | 厨具: {', '.join(recipe['cookware'])}")

            st.write(f"**主料：** {', '.join(recipe.get('ingredients', []))}")
            st.write(f"**调料：** {', '.join(recipe.get('seasonings', []))}")

            # 展示未使用的食材
            unused = recipe.get("unused_ingredients", [])
            if unused:
                st.warning(f"**剩余食材：** {', '.join(unused)}（可留作下顿）")

            st.write("**步骤：**")
            for step in recipe["steps"]:
                st.write(step)

            st.info(f"**注意事项：** {recipe['notes']}")
            st.warning(f"**安全提示：** {recipe['safety']}")

            nutrition = recipe.get("nutrition_notes", "未提供")
            st.success(f"**营养分析：** {nutrition}\n\n*（AI 粗略定性分析，仅供参考）*")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("可行", key=f"good_{i}"):
                    save_feedback(recipe["name"], True)
                    st.toast(f"已反馈：{recipe['name']} 可行")
            with col2:
                if st.button("不可行", key=f"bad_{i}"):
                    save_feedback(recipe["name"], False)
                    st.toast(f"已反馈：{recipe['name']} 不可行")


# --- 主流程 ---
if st.button("生成菜谱", type="primary"):
    if not ingredients:
        st.error("请先输入食材。")
    elif not cookware:
        st.error("请至少选择一个厨具。")
    elif not api_key:
        st.error("请先在左侧配置 API Key。")
    else:
        with st.spinner("AI 正在根据你的库存和约束生成家常菜..."):
            try:
                client = OpenAI(api_key=api_key, base_url=base_url)

                prompt = f"""
                你是一个专为独居人士设计的家常菜谱生成助手。
                用户现有食材：{ingredients}
                可用厨具：{', '.join(cookware)}
                最长烹饪时间：{max_time}分钟
                忌口/过敏：{dietary if dietary else '无'}

                请严格按照以下规则生成3个菜谱：
                1. 只能使用用户提供的厨具。
                2. 总耗时不得超过{max_time}分钟。
                3. 绝对避开用户的忌口/过敏原。
                4. 禁止出现油炸、明火等宿舍/出租屋高危操作。
                5. 【重要】必须是大众熟知的家常菜。绝对禁止创意融合菜或奇葩搭配（如草莓炒肉）。
                6. 【重要】不需要在一道菜里用上用户所有的食材。优先保证菜谱合理且好吃，允许食材剩余，剩下的留作下顿。

                调料假设：用户默认有基础调料（盐、油、生抽、醋、糖等）。

                营养分析要求：只做非常粗略的定性描述，绝对禁止输出具体卡路里数值或克数。

                必须返回一个 JSON 数组，不要包含任何 markdown 标记（如 ```json）。
                每个对象包含以下字段：
                "name": "菜名",
                "time": 耗时(整数),
                "cookware": ["厨具1"],
                "ingredients": ["本菜谱使用的主料"],
                "unused_ingredients": ["用户输入了但本菜谱没用上的食材"],
                "seasonings": ["调料1"],
                "steps": ["步骤1"],
                "notes": "注意事项",
                "safety": "安全提示",
                "nutrition_notes": "粗略定性营养描述"
                """

                response = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.5
                )

                content = response.choices[0].message.content
                parsed = json.loads(content)
                if isinstance(parsed, dict) and "recipes" in parsed:
                    recipes = parsed["recipes"]
                elif isinstance(parsed, dict):
                    recipes = next(v for v in parsed.values() if isinstance(v, list))
                else:
                    recipes = parsed

                st.success("AI 生成成功！")
                st.session_state.recipes = recipes[:3]

            except Exception as e:
                st.error(f"API 调用失败：{e}")

if "recipes" in st.session_state and st.session_state.recipes:
    render_recipes(st.session_state.recipes)