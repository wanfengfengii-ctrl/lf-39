import http.client
import json
import urllib.parse

BASE_URL = "127.0.0.1:8000"

def api_request(path, method="GET", data=None):
    conn = http.client.HTTPConnection(BASE_URL)
    headers = {"Accept": "application/json"}
    body = None
    if data is not None:
        body = json.dumps(data)
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    resp_data = resp.read().decode()
    conn.close()
    try:
        return resp.status, json.loads(resp_data)
    except:
        return resp.status, resp_data

def create_project():
    conn = http.client.HTTPConnection(BASE_URL)
    conn.request("POST", "/api/projects", 
        body=urllib.parse.urlencode({"name": "综合测试项目3"}),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = conn.getresponse()
    location = resp.getheader("Location", "") or resp.getheader("location", "")
    resp.read()
    conn.close()
    return int(location.rstrip("/").split("/")[-1])

print("=" * 60)
print("  综合问题测试")
print("=" * 60)

project_id = create_project()
print(f"\n✅ 项目: {project_id}")

# 添加上壶和下壶
status, data = api_request(f"/api/projects/{project_id}/multi-vessel/vessels", "POST", {
    "level_index": 0, "name": "上壶", "role": "top",
    "capacity": 800.0, "water_inlet_type": "constant",
    "outlet_diameter": 4.0, "target_duration": 60.0, "initial_level": 800.0
})
top_id = data["vessel"]["id"]
print(f"✅ 上壶: {top_id}")

status, data = api_request(f"/api/projects/{project_id}/multi-vessel/vessels", "POST", {
    "level_index": 1, "name": "下壶", "role": "bottom",
    "capacity": 600.0, "water_inlet_type": "gravity",
    "outlet_diameter": 3.0, "target_duration": 60.0, "initial_level": 0.0
})
bottom_id = data["vessel"]["id"]
print(f"✅ 下壶: {bottom_id}")

print("\n" + "-" * 40)
print("问题3测试: 重复添加流量关系")
print("-" * 40)

status1, data1 = api_request(f"/api/projects/{project_id}/multi-vessel/relations", "POST", {
    "upstream_vessel_id": top_id, "downstream_vessel_id": bottom_id,
    "flow_coefficient": 0.95, "delay_seconds": 2.0, "relation_type": "series"
})
print(f"第一次添加: ok={data1.get('ok')}, msg={data1.get('error','无错误')}")

status2, data2 = api_request(f"/api/projects/{project_id}/multi-vessel/relations", "POST", {
    "upstream_vessel_id": top_id, "downstream_vessel_id": bottom_id,
    "flow_coefficient": 0.95, "delay_seconds": 2.0, "relation_type": "series"
})
print(f"第二次添加（应该失败）: ok={data2.get('ok')}, msg={data2.get('error','无错误')}")
if data2.get("ok"):
    print("❌ 问题3存在: 重复添加成功了！")
else:
    print("✅ 问题3: 重复关系检查正常工作")

print("\n" + "-" * 40)
print("问题1测试: 时间节点顺序")
print("-" * 40)

status, data = api_request(f"/api/projects/{project_id}/multi-vessel/experiments", "POST")
exp_id = data["experiment"]["id"]
print(f"✅ 实验: {exp_id}")

# 测试1：先录5，再录3（应该失败）
status, data = api_request(
    f"/api/projects/{project_id}/multi-vessel/experiments/{exp_id}/records", "POST",
    {"time_point": 5.0, "records": [
        {"vessel_id": top_id, "time_point": 5.0, "water_level": 750.0},
        {"vessel_id": bottom_id, "time_point": 5.0, "water_level": 40.0},
    ]}
)
print(f"录入 t=5: ok={data.get('ok')}, msg={data.get('error','无错误')}")

status, data = api_request(
    f"/api/projects/{project_id}/multi-vessel/experiments/{exp_id}/records", "POST",
    {"time_point": 3.0, "records": [
        {"vessel_id": top_id, "time_point": 3.0, "water_level": 770.0},
        {"vessel_id": bottom_id, "time_point": 3.0, "water_level": 20.0},
    ]}
)
print(f"录入 t=3 (应该失败): ok={data.get('ok')}, msg={data.get('error','无错误')}")
if data.get("ok"):
    print("❌ 问题1存在: 顺序错乱录入成功了！")
else:
    print("✅ 问题1: 时间顺序检查正常工作")

# 测试2：只录了上壶的5，下壶能不能录3？（不同容器不同时间点）
print("\n--- 测试不同容器独立时间 ---")
# 创建新实验
status, data = api_request(f"/api/projects/{project_id}/multi-vessel/experiments", "POST")
exp_id2 = data["experiment"]["id"]
print(f"✅ 新实验2: {exp_id2}")

# 只录上壶 t=5
status, data = api_request(
    f"/api/projects/{project_id}/multi-vessel/experiments/{exp_id2}/records", "POST",
    {"time_point": 5.0, "records": [
        {"vessel_id": top_id, "time_point": 5.0, "water_level": 750.0},
    ]}
)
print(f"上壶 t=5: ok={data.get('ok')}, msg={data.get('error','无错误')}")

# 再录下壶 t=3（时间比上壶的5小，但这是一个新的batch的time_point=3）
status, data = api_request(
    f"/api/projects/{project_id}/multi-vessel/experiments/{exp_id2}/records", "POST",
    {"time_point": 3.0, "records": [
        {"vessel_id": bottom_id, "time_point": 3.0, "water_level": 20.0},
    ]}
)
print(f"下壶 batch t=3 (应该失败): ok={data.get('ok')}, msg={data.get('error','无错误')}")
if data.get("ok"):
    print("❌ 问题1变种: 全局最大时间检查可能有漏洞？")
else:
    print("✅ 全局时间检查正常工作")

print("\n" + "-" * 40)
print("问题2测试: 理论刻度线数据是否存在")
print("-" * 40)

# 直接获取上壶刻度方案
status, data = api_request(
    f"/api/projects/{project_id}/multi-vessel/vessels/{top_id}/scale", "GET"
)
print(f"上壶刻度: ok={data.get('ok')}, vessel_id={data.get('scheme',{}).get('vessel_id')}, marks={len(data.get('scheme',{}).get('marks',[]))}")
if data.get("ok") and data.get("scheme"):
    s = data["scheme"]
    print(f"  vessel_id={s.get('vessel_id')},  marks样本:")
    for m in s.get("marks", [])[:3]:
        print(f"    t={m['target_time']}分 → {m['target_water_level']}ml")
    if not s.get("vessel_id"):
        print("  ❌ 问题2: scale返回没有vessel_id，前端无法关联到容器！")
    else:
        print("  ✅ 刻度方案有vessel_id")
else:
    print("  ❌ 获取刻度方案失败")

print("\n" + "=" * 60)
print("完成")
