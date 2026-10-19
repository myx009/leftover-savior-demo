import streamlit as st
import json
import csv
import os
import datetime
import re
from openai import OpenAI

st.title("青空冰箱 Clear Fridge")
st.caption("你的智能库存与家常菜谱管家")

# --- 侧边栏 ---
with st.sidebar:
    st.header("配置")
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
        st.success("API Key 已自动加载")
    except Exception:
        api_key = st.text_input("API Key", type="password", help="输入 DeepSeek 或兼容 OpenAI 格式的 Key")
    model_name = st.text_input("模型", value="deepseek-chat")
    base_url = st.text_input("Base URL", value="https://api.deepseek.com")

st.subheader("1. 输入现有食材")
ingredients = st.text_area("食材列表（最多10种）", placeholder="例如：半个土豆、一根火腿肠、两个鸡蛋、半个洋葱", height=100)

st.subheader("2. 设置硬约束")
preset_cookware = ["电煮锅", "微波炉", "平底锅", "烤箱", "空气炸锅", "电饭煲"]
selected_cookware = st.multiselect("可用厨具（至少选1个）", preset_cookware)
custom_cookware = st.text_input("自定义厨具（可选，多个用逗号分隔）")
custom_cookware_list = [c.strip() for c in custom_cookware.split(",") if c.strip()] if custom_cookware else []
cookware = selected_cookware + custom_cookware_list

time_option = st.radio("最长烹饪时间", ["10分钟", "20分钟", "30分钟", "自定义"], horizontal=True)
if time_option == "自定义":
    max_time = st.number_input("自定义分钟数", min_value=1, max_value=120, value=15, step=1)
else:
    max_time = int(time_option.replace("分钟", ""))

dietary = st.text_input("忌口 / 过敏（可留空）", placeholder="例如：不要辣、不吃香菜")

st.divider()

def save_feedback(recipe_name, action):
    try:
        _ = st.secrets["OPENAI_API_KEY"]
        is_cloud = True
    except Exception:
        is_cloud = False
    if not is_cloud:
        file_exists = os.path.isfile("feedback.csv")
        with open("feedback.csv", "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "recipe_name", "action"])
            writer.writerow([datetime.datetime.now().isoformat(), recipe_name, action])

# --- 辅助清洗函数 ---
def safe_list(val):
    """强制将任何类型转为字符串列表"""
    if isinstance(val, list):
        return [str(v) for v in val]
    elif isinstance(val, str):
        return [val]
    return []

def clean_time(val):
    """提取数字，比如 '28分钟' -> 28"""
    if isinstance(val, int) or isinstance(val, float):
        return val
    if isinstance(val, str):
        nums = re.findall(r'\d+', val)
        if nums:
            return int(nums[0])
    return "未知"

# --- 渲染卡片函数 ---
def render_recipes(recipes, all_recipes):
    cols = st.columns(3)
    for i, col in enumerate(cols):
        with col:
            recipe = recipes[i]
            name = recipe.get("name", f"神秘菜谱 {i+1}")
            # 清洗时间
            time_val = clean_time(recipe.get("time", "未知"))
            
            # 清洗厨具
            cookware_list = safe_list(recipe.get("cookware", []))
            cookware_str = ', '.join(cookware_list) if cookware_list else "未知"
            
            st.subheader(name)
            st.caption(f"耗时: {time_val}分钟 | 厨具: {cookware_str}")
            
            # 清洗主料和调料
            ing_list = safe_list(recipe.get("ingredients", []))
            sea_list = safe_list(recipe.get("seasonings", []))
            st.write(f"**主料：** {', '.join(ing_list)}")
            st.write(f"**调料：** {', '.join(sea_list) if sea_list else '无'}")
            
            unused = safe_list(recipe.get("unused_ingredients", []))
            if unused:
                st.warning(f"**剩余食材：** {', '.join(unused)}（可留作下顿）")

            st.write("**步骤：**")
            for step in safe_list(recipe.get("steps", ["暂无步骤"])):
                st.write(step)

            st.info(f"**注意事项：** {recipe.get('notes', '无')}")
            st.warning(f"**安全提示：** {recipe.get('safety', '无')}")
            st.success(f"**营养分析：** {recipe.get('nutrition_notes', '未提供')}\n\n*（AI 粗略定性分析，仅供参考）*")

            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("可行", key=f"good_{i}"):
                    save_feedback(name, "可行")
                    st.toast(f"已反馈：{name} 可行")
            with col2:
                if st.button("不可行", key=f"bad_{i}"):
                    save_feedback(name, "不可行")
                    st.toast(f"已反馈：{name} 不可行")
            with col3:
                if st.button("换一个 🔄", key=f"change_{i}"):
                    blacklist = [r.get("name", "") for r in all_recipes if r.get("name") != name]
                    blacklist += st.session_state.history_recipes
                    blacklist_str = "、".join(list(set(blacklist)))

                    with st.spinner("正在换新菜..."):
                        try:
                            client = OpenAI(api_key=api_key, base_url=base_url)
                            change_prompt = f"""
                            你是一个家常菜谱生成助手。用户现有食材：{ingredients}。
                            可用厨具：{', '.join(cookware)}。最长烹饪时间：{max_time}分钟。忌口：{dietary}。
                            
                            现在用户想换掉这道菜：【{name}】。
                            绝对禁止生成以下黑名单中的菜品：{blacklist_str}。
                            
                            要求：
                            1. 生成1个全新的家常菜，耗时在 {max_time-5 if max_time>5 else 1}-{max_time} 分钟之间。
                            2. 必须使用可用厨具，无高危操作。
                            3. 必须返回 JSON 格式，严格遵循字段规范（见下文）。
                            """
                            res = client.chat.completions.create(
                                model=model_name,
                                messages=[{"role": "user", "content": change_prompt}],
                                response_format={"type": "json_object"},
                                temperature=0.8
                            )
                            
                            parsed_new = json.loads(res.choices[0].message.content)
                            
                            new_recipe = parsed_new
                            if isinstance(parsed_new, dict):
                                if "name" not in parsed_new:
                                    for val in parsed_new.values():
                                        if isinstance(val, dict) and "name" in val:
                                            new_recipe = val
                                            break
                                        elif isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict) and "name" in val[0]:
                                            new_recipe = val[0]
                                            break
                            
                            if "name" not in new_recipe:
                                st.error("AI 返回数据异常，请重试。")
                            else:
                                st.session_state.recipes[i] = new_recipe
                                st.session_state.history_recipes.append(new_recipe["name"])
                                save_feedback(name, "换一个")
                                st.rerun() 
                        except Exception as e:
                            st.error(f"生成失败：{e}")

if "history_recipes" not in st.session_state:
    st.session_state.history_recipes = []

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
                history_str = "、".join(st.session_state.history_recipes[-10:]) if st.session_state.history_recipes else "无"

                # 这里在 Prompt 中强化了格式要求
                prompt = f"""
                你是一个专为独居人士设计的家常菜谱生成助手。
                用户现有食材：{ingredients}
                可用厨具：{', '.join(cookware)}
                最长烹饪时间限制：{max_time}分钟
                忌口/过敏：{dietary if dietary else '无'}
                【历史已推荐菜品】：{history_str}

                请严格按照以下规则生成3个菜谱：
                1. 只能使用用户提供的厨具。
                2. 【时间强制约束】这道菜的真实总耗时必须严格在 {max_time-5 if max_time>5 else 1} 到 {max_time} 分钟之间。
                3. 绝对避开用户的忌口/过敏原。
                4. 禁止出现油炸、明火等宿舍/出租屋高危操作。
                5. 【重要】必须是大众熟知的家常菜。绝对禁止创意融合菜。
                6. 【重要】允许食材剩余。
                7. 【防重复约束】绝对禁止生成【历史已推荐菜品】中的任何菜品。

                营养分析要求：非常粗略的定性描述，禁止具体卡路里数值。

                【严格格式要求】：必须返回一个 JSON 对象，包含 "recipes" 字段，该字段是一个数组。
                数组中每个对象的格式如下：
                - "name": 字符串
                - "time": 纯数字 (例如 10，绝对不要加 "分钟" 两个字)
                - "cookware": 字符串数组
                - "ingredients": 字符串数组 (只能放主料，不要把盐、油等调料放进来)
                - "seasonings": 字符串数组 (放调料)
                - "steps": 字符串数组
                - "unused_ingredients": 字符串数组
                - "notes": 字符串
                - "safety": 字符串
                - "nutrition_notes": 字符串
                """

                response = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.8
                )

                content = response.choices[0].message.content
                parsed = json.loads(content)
                if isinstance(parsed, dict) and "recipes" in parsed:
                    recipes = parsed["recipes"]
                elif isinstance(parsed, dict):
                    recipes = next((v for v in parsed.values() if isinstance(v, list)), [])
                else:
                    recipes = parsed

                st.success("AI 生成成功！")
                st.session_state.recipes = recipes[:3]
                
                for r in recipes[:3]:
                    if "name" in r and r["name"] not in st.session_state.history_recipes:
                        st.session_state.history_recipes.append(r["name"])

            except Exception as e:
                st.error(f"API 调用失败：{e}")

if "recipes" in st.session_state and st.session_state.recipes:
    render_recipes(st.session_state.recipes, st.session_state.recipes)
