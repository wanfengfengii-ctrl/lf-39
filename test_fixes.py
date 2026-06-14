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
        body=urllib.parse.urlencode({"name": "验证修复测试项目"}),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = conn.getresponse()
    location = resp.getheader("Location", "") or resp.getheader("location", "")
    resp.read()
    conn.close()
    return int(location.rstrip("/").split("/")[-1])

print("=" * 60)
print("  修复验证测试")
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

status, data = api_request(f"/api/projects/{project_id}/multi-vessel/vessels", "POST", {
    "level_index": 1, "name": "下壶", "role": "bottom",
    "capacity": 600.0, "water_inlet_type": "gravity",
    "outlet_diameter": 3.0, "target_duration": 60.0, "initial_level": 0.0
})
bottom_id = data["vessel"]["id"]
print(f"✅ 容器: 上壶={top_id}, 下壶={bottom_id}")

# 添加流量关系
status, data = api_request(f"/api/projects/{project_id}/multi-vessel/relations", "POST", {
    "upstream_vessel_id": top_id, "downstream_vessel_id": bottom_id,
    "flow_coefficient": 0.95, "delay_seconds": 2.0, "relation_type": "series"
})
print(f"✅ 添加流量关系: ok={data.get('ok')}")

# 创建实验
status, data = api_request(f"/api/projects/{project_id}/multi-vessel/experiments", "POST")
exp_id = data["experiment"]["id"]
print(f"✅ 实验: {exp_id}")

# 录入数据
for t in [0, 10, 20, 30, 40, 50, 60]:
    top_level = 800.0 - t * 10.0
    bottom_level = min(t * 9.0, 550.0)
    status, data = api_request(
        f"/api/projects/{project_id}/multi-vessel/experiments/{exp_id}/records", "POST",
        {"time_point": float(t), "records": [
            {"vessel_id": top_id, "time_point": float(t), "water_level": round(top_level, 2)},
            {"vessel_id": bottom_id, "time_point": float(t), "water_level": round(bottom_level, 2)}
        ]}
    )
print("✅ 录入7个时间节点数据")

# finalize 并验证返回结构
print("\n" + "-" * 50)
print("验证问题2修复: finalize返回vessel_scale_schemes")
print("-" * 50)
status, data = api_request(
    f"/api/projects/{project_id}/multi-vessel/experiments/{exp_id}/finalize", "POST"
)
print(f"  status={status}, ok={data.get('ok')}")
print(f"  字段: avg_error={data.get('avg_error')}, record_count={data.get('record_count')}")
print(f"  vessel_records: {len(data.get('vessel_records', []))} 条")
schemes = data.get("vessel_scale_schemes", [])
print(f"  vessel_scale_schemes: {len(schemes)} 个")
for s in schemes:
    print(f"    - vessel_id={s.get('vessel_id')}, marks={len(s.get('marks', []))} 个刻度")
if schemes and all(s.get('vessel_id') for s in schemes):
    print("  ✅ 问题2修复：finalize返回了所有容器的刻度方案，且都有vessel_id")
else:
    print("  ❌ 问题2：刻度方案数据有问题")

# 验证analysis API也返回
print("\n" + "-" * 50)
print("验证analysis API也返回vessel_scale_schemes")
print("-" * 50)
status, data = api_request(f"/api/projects/{project_id}/multi-vessel/analysis?exp_id={exp_id}")
print(f"  status={status}, ok={data.get('ok')}")
analysis = data.get("analysis", {})
schemes = data.get("vessel_scale_schemes", [])
print(f"  analysis.time_series: {len(analysis.get('time_series', []))} 个容器序列")
print(f"  vessel_scale_schemes: {len(schemes)} 个")
for s in schemes:
    print(f"    - vessel_id={s.get('vessel_id')}, marks={len(s.get('marks', []))} 个刻度")
if schemes and all(s.get('vessel_id') for s in schemes):
    print("  ✅ 问题2修复：analysis API也返回了刻度方案")
else:
    print("  ❌ 问题2：刻度方案数据有问题")

print("\n" + "=" * 60)
print("所有修复验证完成！")
