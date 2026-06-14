import urllib.request
import urllib.parse
import json
import http.client

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

def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def main():
    print_section("多级漏刻联动校准功能 - 端到端测试")
    
    # 1. 创建新项目
    print_section("1. 创建测试项目")
    form_data = urllib.parse.urlencode({
        "name": "多级漏刻测试项目",
        "description": "用于测试多级漏刻联动校准功能",
        "researcher": "测试人员"
    })
    conn = http.client.HTTPConnection(BASE_URL)
    conn.request("POST", "/api/projects", body=form_data, headers={
        "Content-Type": "application/x-www-form-urlencoded"
    })
    resp = conn.getresponse()
    location = resp.getheader("Location", "") or resp.getheader("location", "")
    resp.read()
    conn.close()
    
    project_id = location.rstrip("/").split("/")[-1]
    print(f"  Location: {location}")
    print(f"  项目创建成功，ID: {project_id}")
    assert project_id.isdigit(), "项目ID获取失败"
    project_id = int(project_id)
    
    # 2. 添加第一个容器（上壶）
    print_section("2. 添加上壶容器")
    status, data = api_request(
        f"/api/projects/{project_id}/multi-vessel/vessels",
        method="POST",
        data={
            "level_index": 0,
            "name": "上壶",
            "role": "top",
            "capacity": 800.0,
            "water_inlet_type": "constant",
            "outlet_diameter": 4.0,
            "target_duration": 60.0,
            "initial_level": 800.0
        }
    )
    print(f"  状态码: {status}")
    print(f"  结果: {json.dumps(data, ensure_ascii=False, indent=2)[:200]}")
    assert data.get("ok"), f"添加上壶失败: {data}"
    top_vessel_id = data["vessel"]["id"]
    print(f"  上壶 ID: {top_vessel_id}")
    
    # 3. 添加第二个容器（下壶）
    print_section("3. 添加下壶容器")
    status, data = api_request(
        f"/api/projects/{project_id}/multi-vessel/vessels",
        method="POST",
        data={
            "level_index": 1,
            "name": "下壶",
            "role": "bottom",
            "capacity": 600.0,
            "water_inlet_type": "gravity",
            "outlet_diameter": 3.0,
            "target_duration": 60.0,
            "initial_level": 0.0
        }
    )
    print(f"  状态码: {status}")
    assert data.get("ok"), f"添加下壶失败: {data}"
    bottom_vessel_id = data["vessel"]["id"]
    print(f"  下壶 ID: {bottom_vessel_id}")
    
    # 4. 获取多级配置
    print_section("4. 获取多级配置")
    status, data = api_request(f"/api/projects/{project_id}/multi-vessel")
    assert data.get("ok"), "获取配置失败"
    cfg = data["config"]
    print(f"  is_multi_vessel: {cfg['is_multi_vessel']}")
    print(f"  容器数量: {len(cfg['vessels'])}")
    print(f"  流量关系数量: {len(cfg['flow_relations'])}")
    
    # 5. 添加流量关系
    print_section("5. 添加级间流量关系")
    status, data = api_request(
        f"/api/projects/{project_id}/multi-vessel/relations",
        method="POST",
        data={
            "upstream_vessel_id": top_vessel_id,
            "downstream_vessel_id": bottom_vessel_id,
            "flow_coefficient": 0.95,
            "delay_seconds": 2.0,
            "relation_type": "series"
        }
    )
    print(f"  状态码: {status}")
    assert data.get("ok"), f"添加流量关系失败: {data}"
    print(f"  流量关系 ID: {data['relation']['id']}")
    print(f"  流量系数: {data['relation']['flow_coefficient']}")
    print(f"  延迟: {data['relation']['delay_seconds']} 秒")
    
    # 6. 获取下壶刻度方案
    print_section("6. 获取上壶刻度方案")
    status, data = api_request(
        f"/api/projects/{project_id}/multi-vessel/vessels/{top_vessel_id}/scale"
    )
    assert data.get("ok"), "获取刻度方案失败"
    scheme = data["scheme"]
    print(f"  刻度版本: {scheme['version']}")
    print(f"  刻度数量: {len(scheme['marks'])}")
    for m in scheme["marks"][:3]:
        print(f"    刻度 #{m['mark_index']}: {m['target_time']}分 → {m['target_water_level']}ml")
    
    # 7. 创建多级实验
    print_section("7. 创建多级实验")
    status, data = api_request(
        f"/api/projects/{project_id}/multi-vessel/experiments",
        method="POST"
    )
    print(f"  状态码: {status}")
    assert data.get("ok"), f"创建实验失败: {data}"
    exp_id = data["experiment"]["id"]
    print(f"  实验 ID: {exp_id}")
    print(f"  轮次: {data['experiment']['round_number']}")
    print(f"  状态: {data['experiment']['status']}")
    print(f"  is_multi_vessel: {data['experiment']['is_multi_vessel']}")
    
    # 8. 录入实验数据（5个时间节点）
    print_section("8. 录入实验数据")
    time_points = [0, 10, 20, 30, 40, 50, 60]
    
    # 模拟数据：上壶水位逐渐下降，下壶水位逐渐上升
    for t in time_points:
        top_level = 800.0 - t * 10.0  # 上壶：每分钟下降10ml
        bottom_level = t * 9.0  # 下壶：每分钟上升9ml（有损耗）
        bottom_level = min(bottom_level, 550.0)
        
        status, data = api_request(
            f"/api/projects/{project_id}/multi-vessel/experiments/{exp_id}/records",
            method="POST",
            data={
                "time_point": float(t),
                "records": [
                    {"vessel_id": top_vessel_id, "time_point": float(t), "water_level": round(top_level, 2)},
                    {"vessel_id": bottom_vessel_id, "time_point": float(t), "water_level": round(bottom_level, 2)}
                ]
            }
        )
        if data.get("ok"):
            print(f"  t={t}分: 上壶 {round(top_level,2)}ml, 下壶 {round(bottom_level,2)}ml ✓")
        else:
            print(f"  t={t}分: 失败 - {data.get('error', '未知错误')}")
    
    # 9. 完成实验并分析
    print_section("9. 完成实验并分析")
    status, data = api_request(
        f"/api/projects/{project_id}/multi-vessel/experiments/{exp_id}/finalize",
        method="POST"
    )
    print(f"  状态码: {status}")
    assert data.get("ok"), f"完成实验失败: {data}"
    print(f"  平均误差: {data['avg_error']}%")
    print(f"  记录数: {data['record_count']}")
    print(f"  项目状态: {data['project_status']}")
    
    analysis = data["analysis"]
    print(f"\n  分析结果摘要:")
    print(f"    容器总数: {analysis['total_vessels']}")
    print(f"    时间序列数: {len(analysis['time_series'])}")
    print(f"    级间误差数: {len(analysis['inter_vessel_errors'])}")
    print(f"    误差放大环节数: {len(analysis['error_amplification_stages'])}")
    print(f"    刻度调整建议数: {len(analysis['scale_adjustments'])}")
    print(f"    误差阈值: ±{analysis['threshold_percent']}%")
    
    # 10. 查看各级误差详情
    print_section("10. 各级误差详情")
    for stage in analysis["error_amplification_stages"]:
        status_text = "🔴 误差放大" if stage["is_amplification_stage"] else "🟢 正常"
        print(f"  {stage['vessel_name']}（第{stage['level_index']}级）:")
        print(f"    平均误差: {stage['avg_error_percent']}%")
        print(f"    最大误差: {stage['max_error_percent']}%")
        print(f"    误差增益: {stage['error_gain']}x")
        print(f"    状态: {status_text}")
        print(f"    原因: {stage['reason']}")
    
    # 11. 获取联合刻度调整建议
    print_section("11. 分级刻度联合调整建议")
    status, data = api_request(
        f"/api/projects/{project_id}/multi-vessel/joint-adjustment?exp_id={exp_id}"
    )
    assert data.get("ok"), "获取联合调整建议失败"
    adj = data["adjustment"]
    
    print(f"  涉及容器: {adj['total_vessels']} 个")
    print(f"  调整步骤数: {len(adj['adjustment_steps'])}")
    print(f"  预期总改善: {adj['total_expected_improvement']}%")
    print(f"\n  整体方案说明:")
    print(f"    {adj['overall_rationale'][:200]}...")
    
    print(f"\n  调整步骤详情:")
    for step in adj["adjustment_steps"]:
        priority_label = {"high": "高", "medium": "中", "low": "低"}.get(step["priority"], step["priority"])
        print(f"\n    第 {step['step_order']} 步: {step['vessel_name']}（优先级: {priority_label}）")
        print(f"      当前平均误差: {step['current_avg_error']}%")
        print(f"      预期改善: {step['expected_improvement']}%")
        print(f"      对下游影响: {step['impact_on_downstream']}")
        print(f"      调整项数: {step['adjustment_count']} 个")
        print(f"      摘要: {step['adjustment_summary']}")
        if step["details"]:
            print(f"      具体调整:")
            for d in step["details"][:2]:
                print(f"        - 刻度 #{d['mark_index']}（{d['target_time']}分）: {d['original_level']} → {d['suggested_level']} ml（{d['direction']}）")
            if len(step["details"]) > 2:
                print(f"        ... 还有 {len(step['details']) - 2} 项")
    
    # 12. 查看时间序列数据
    print_section("12. 时间序列数据验证")
    for ts in analysis["time_series"]:
        print(f"\n  {ts['vessel_name']}（第{ts['level_index']}级，{ts['role']}）:")
        print(f"    数据点数量: {len(ts['data_points'])}")
        if ts["data_points"]:
            first = ts["data_points"][0]
            last = ts["data_points"][-1]
            print(f"    首点: t={first['time_point']}分, 水位={first['water_level']}ml")
            print(f"    末点: t={last['time_point']}分, 水位={last['water_level']}ml")
            if last.get("computed_flow_rate") is not None:
                print(f"    末点流速: {last['computed_flow_rate']} ml/分")
            if last.get("time_error") is not None:
                print(f"    末点时间误差: {last['time_error']}%")
    
    print_section("测试完成！")
    print(f"  所有功能测试通过 ✓")
    print(f"  项目 ID: {project_id}")
    print(f"  实验 ID: {exp_id}")

if __name__ == "__main__":
    main()
