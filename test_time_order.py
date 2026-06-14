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

# 1. 创建项目
conn = http.client.HTTPConnection(BASE_URL)
conn.request("POST", "/api/projects", 
    body=urllib.parse.urlencode({"name": "时间顺序测试项目"}),
    headers={"Content-Type": "application/x-www-form-urlencoded"})
resp = conn.getresponse()
location = resp.getheader("Location", "") or resp.getheader("location", "")
resp.read()
conn.close()
project_id = int(location.rstrip("/").split("/")[-1])
print(f"✅ 项目创建成功: {project_id}")

# 2. 添加上壶
status, data = api_request(f"/api/projects/{project_id}/multi-vessel/vessels", "POST", {
    "level_index": 0, "name": "上壶", "role": "top",
    "capacity": 800.0, "water_inlet_type": "constant",
    "outlet_diameter": 4.0, "target_duration": 60.0, "initial_level": 800.0
})
assert data.get("ok"), f"添加上壶失败: {data}"
top_id = data["vessel"]["id"]
print(f"✅ 上壶添加成功: {top_id}")

# 3. 创建实验
status, data = api_request(f"/api/projects/{project_id}/multi-vessel/experiments", "POST")
assert data.get("ok"), f"创建实验失败: {data}"
exp_id = data["experiment"]["id"]
print(f"✅ 实验创建成功: {exp_id}")

# 4. 先录 5 分钟
status, data = api_request(
    f"/api/projects/{project_id}/multi-vessel/experiments/{exp_id}/records", "POST",
    {"time_point": 5.0, "records": [
        {"vessel_id": top_id, "time_point": 5.0, "water_level": 750.0}
    ]}
)
print(f"录入 t=5: status={status}, ok={data.get('ok')}, msg={data.get('error','')}")
assert data.get("ok"), f"录入 t=5 失败: {data}"

# 5. 再录 3 分钟——应该报错
status, data = api_request(
    f"/api/projects/{project_id}/multi-vessel/experiments/{exp_id}/records", "POST",
    {"time_point": 3.0, "records": [
        {"vessel_id": top_id, "time_point": 3.0, "water_level": 770.0}
    ]}
)
print(f"录入 t=3 (应该失败): status={status}, ok={data.get('ok')}, msg={data.get('error','')}")
if data.get("ok"):
    print("❌ 问题确认: 时间节点没有按先后顺序限制！")
else:
    print("✅ 时间顺序验证正常工作")
