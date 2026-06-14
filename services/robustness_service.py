from __future__ import annotations

import math
import random
from datetime import datetime
from typing import List, Dict, Tuple, Optional

from sqlalchemy.orm import Session

from database import models
from schemas import (
    PerturbationConfigUpdate, PerturbationConfigOut,
    SimulationScenarioOut, SimulationResultPoint, SimulationScenarioDetail,
    SensitivityScore, ParameterRanking, CalibrationAdvice, ScenarioSummary,
    RobustnessAssessmentOut, BatchSimulationOut,
)
from services.validation_service import ValidationError


PARAM_LABELS = {
    "temperature": "环境温度",
    "viscosity": "液体黏度",
    "inflow_amplitude": "注水波动幅度",
    "orifice_wear": "孔径磨损程度",
    "tilt_angle": "容器倾斜角度",
}

PARAM_CATEGORIES = {
    "temperature": "环境因素",
    "viscosity": "物理参数",
    "inflow_amplitude": "供水系统",
    "orifice_wear": "器件老化",
    "tilt_angle": "机械结构",
}

PARAM_DESCRIPTIONS = {
    "temperature": "环境温度变化影响液体黏度和蒸发速率",
    "viscosity": "液体黏度直接影响出流速度，黏度越高流速越慢",
    "inflow_amplitude": "上壶注水波动会传导至各级水位稳定性",
    "orifice_wear": "长期使用导致出水孔径扩大，流速加快",
    "tilt_angle": "容器倾斜改变有效液位高度，影响静水压力",
}


def _water_viscosity(temperature_c: float) -> float:
    t = temperature_c
    a = 1.002e-3
    b = 1.2378
    c = -1.303e-3
    d = 3.06e-6
    eta_20 = 1.002e-3
    ratio = math.exp(b * (20 - t) / (t + 96) + c * (20 - t) + d * (20 - t) ** 2)
    return eta_20 * ratio


def _viscosity_correction_factor(temperature_c: float, baseline_temp: float = 20.0) -> float:
    eta_current = _water_viscosity(temperature_c)
    eta_baseline = _water_viscosity(baseline_temp)
    if eta_baseline < 1e-12:
        return 1.0
    return eta_baseline / eta_current


def _tilt_correction_factor(tilt_angle_deg: float) -> float:
    angle_rad = math.radians(tilt_angle_deg)
    return math.cos(angle_rad)


def _orifice_diameter_after_wear(base_diameter_mm: float, wear_ratio: float) -> float:
    wear = max(0.0, min(1.0, wear_ratio))
    return base_diameter_mm * (1.0 + wear)


def _inflow_fluctuation(
    t_minutes: float,
    base_inflow: float,
    amplitude: float,
    frequency: float,
    phase: float = 0.0,
) -> float:
    if amplitude <= 0 or frequency <= 0:
        return base_inflow
    fluctuation = amplitude * base_inflow * math.sin(2 * math.pi * frequency * t_minutes / 60.0 + phase)
    return max(0.0, base_inflow + fluctuation)


def _compute_outflow_rate(
    water_level_ml: float,
    capacity_ml: float,
    outlet_diameter_mm: float,
    viscosity_factor: float = 1.0,
    tilt_factor: float = 1.0,
    cross_section_cm2: float = 50.0,
) -> float:
    if water_level_ml <= 0:
        return 0.0
    height_cm = (water_level_ml / capacity_ml) * 10.0 * tilt_factor
    if height_cm <= 0:
        return 0.0
    g = 981.0
    orifice_radius_cm = outlet_diameter_mm / 20.0
    orifice_area_cm2 = math.pi * (orifice_radius_cm ** 2)
    velocity_cm_s = math.sqrt(2 * g * height_cm) * viscosity_factor
    if velocity_cm_s <= 0:
        return 0.0
    outflow_cm3_s = 0.61 * orifice_area_cm2 * velocity_cm_s
    return outflow_cm3_s * 60.0


class PerturbationPhysics:

    @staticmethod
    def apply_perturbations(
        base_params: Dict,
        perturbations: Dict,
        t: float,
    ) -> Dict:
        result = dict(base_params)
        temp = perturbations.get("temperature", 20.0)
        baseline_temp = perturbations.get("baseline_temperature", 20.0)
        viscosity_factor = _viscosity_correction_factor(temp, baseline_temp)
        if perturbations.get("viscosity"):
            viscosity_factor = viscosity_factor / perturbations["viscosity"]

        tilt_angle = perturbations.get("tilt_angle", 0.0)
        tilt_factor = _tilt_correction_factor(tilt_angle)

        wear_ratio = perturbations.get("orifice_wear", 0.0)
        base_diameter = result.get("outlet_diameter", 3.0)
        effective_diameter = _orifice_diameter_after_wear(base_diameter, wear_ratio)

        result["viscosity_factor"] = viscosity_factor
        result["tilt_factor"] = tilt_factor
        result["effective_diameter"] = effective_diameter
        return result

    @staticmethod
    def simulate_single_vessel(
        capacity_ml: float,
        outlet_diameter_mm: float,
        target_duration_min: float,
        marks: List[models.ScaleMark],
        perturbations: Dict,
        duration_min: float,
        time_step_min: float,
    ) -> List[Dict]:
        results = []
        current_level = float(capacity_ml)
        base_inflow = 0.0
        inflow_amp = perturbations.get("inflow_amplitude", 0.0)
        inflow_freq = perturbations.get("inflow_frequency", 0.5)
        baseline_temp = perturbations.get("baseline_temperature", 20.0)

        for step_idx in range(int(duration_min / time_step_min) + 1):
            t = round(step_idx * time_step_min, 4)
            if t > duration_min:
                break

            temp = perturbations.get("temperature", 20.0)
            viscosity_factor = _viscosity_correction_factor(temp, baseline_temp)
            if perturbations.get("viscosity"):
                viscosity_factor = viscosity_factor / perturbations["viscosity"]

            tilt_angle = perturbations.get("tilt_angle", 0.0)
            tilt_factor = _tilt_correction_factor(tilt_angle)

            wear_ratio = perturbations.get("orifice_wear", 0.0) * (t / max(duration_min, 1e-6))
            effective_diameter = _orifice_diameter_after_wear(outlet_diameter_mm, wear_ratio)

            actual_inflow = _inflow_fluctuation(t, base_inflow, inflow_amp, inflow_freq)

            outflow = _compute_outflow_rate(
                current_level, capacity_ml, effective_diameter,
                viscosity_factor, tilt_factor,
            )

            net_flow = actual_inflow - outflow
            new_level = max(0.0, current_level + net_flow * time_step_min)

            expected_level = None
            if marks:
                from services.analysis_service import _expected_water_level
                expected_level = _expected_water_level(t, marks, capacity_ml)

            level_error = None
            time_error = None
            if expected_level is not None and expected_level > 0:
                level_error = new_level - expected_level
                time_error = level_error / expected_level * 100.0

            results.append({
                "time_point": t,
                "water_level": round(new_level, 4),
                "expected_level": round(expected_level, 4) if expected_level else None,
                "flow_rate": round(outflow, 4),
                "inflow_rate": round(actual_inflow, 4),
                "time_error": round(time_error, 4) if time_error else None,
                "level_error": round(level_error, 4) if level_error else None,
            })

            current_level = new_level

        return results

    @staticmethod
    def simulate_multi_vessel(
        vessels: List[models.Vessel],
        relations: List[models.VesselFlowRelation],
        vessel_marks: Dict[int, List[models.ScaleMark]],
        perturbations: Dict,
        duration_min: float,
        time_step_min: float,
    ) -> Dict[int, List[Dict]]:
        vessel_map = {v.id: v for v in vessels}
        vessel_levels = {
            v.id: float(v.initial_level or v.capacity)
            for v in vessels
        }
        results_by_vessel: Dict[int, List[Dict]] = {v.id: [] for v in vessels}

        upstream_map: Dict[int, List[models.VesselFlowRelation]] = {}
        for rel in relations:
            if rel.downstream_vessel_id not in upstream_map:
                upstream_map[rel.downstream_vessel_id] = []
            upstream_map[rel.downstream_vessel_id].append(rel)

        inflow_amp = perturbations.get("inflow_amplitude", 0.0)
        inflow_freq = perturbations.get("inflow_frequency", 0.5)
        baseline_temp = perturbations.get("baseline_temperature", 20.0)

        for step_idx in range(int(duration_min / time_step_min) + 1):
            t = round(step_idx * time_step_min, 4)
            if t > duration_min:
                break

            temp = perturbations.get("temperature", 20.0)
            viscosity_factor = _viscosity_correction_factor(temp, baseline_temp)
            if perturbations.get("viscosity"):
                viscosity_factor = viscosity_factor / perturbations["viscosity"]

            tilt_angle = perturbations.get("tilt_angle", 0.0)
            tilt_factor = _tilt_correction_factor(tilt_angle)
            wear_ratio = perturbations.get("orifice_wear", 0.0) * (t / max(duration_min, 1e-6))

            outflows: Dict[int, float] = {}
            for v in vessels:
                effective_diameter = _orifice_diameter_after_wear(v.outlet_diameter, wear_ratio)
                outflows[v.id] = _compute_outflow_rate(
                    vessel_levels[v.id], v.capacity, effective_diameter,
                    viscosity_factor, tilt_factor,
                )

            new_levels = {}
            for v in vessels:
                total_inflow = 0.0

                if v.role == "top" or v.water_inlet_type == "constant":
                    base_inflow = outflows[v.id] if vessel_levels[v.id] > 0 else 0
                    total_inflow = _inflow_fluctuation(t, base_inflow, inflow_amp, inflow_freq)

                up_rels = upstream_map.get(v.id, [])
                for rel in up_rels:
                    if rel.upstream_vessel_id in outflows:
                        delay_min = rel.delay_seconds / 60.0
                        effective_t = max(0.0, t - delay_min)
                        delay_factor = 1.0 if effective_t >= 0 else 0.0
                        total_inflow += outflows[rel.upstream_vessel_id] * rel.flow_coefficient * delay_factor

                net_flow = total_inflow - outflows[v.id]
                new_level = max(0.0, min(v.capacity, vessel_levels[v.id] + net_flow * time_step_min))
                new_levels[v.id] = new_level

            for v in vessels:
                marks = vessel_marks.get(v.id, [])
                expected_level = None
                if marks:
                    from services.analysis_service import _expected_water_level
                    expected_level = _expected_water_level(t, marks, v.capacity)

                level_error = None
                time_error = None
                if expected_level is not None and expected_level > 0:
                    level_error = new_levels[v.id] - expected_level
                    time_error = level_error / expected_level * 100.0

                results_by_vessel[v.id].append({
                    "time_point": t,
                    "water_level": round(new_levels[v.id], 4),
                    "expected_level": round(expected_level, 4) if expected_level else None,
                    "flow_rate": round(outflows[v.id], 4),
                    "inflow_rate": round(total_inflow, 4) if v.id in upstream_map or v.role == "top" else 0.0,
                    "time_error": round(time_error, 4) if time_error else None,
                    "level_error": round(level_error, 4) if level_error else None,
                })

            vessel_levels = new_levels

        return results_by_vessel


class RobustnessService:

    @staticmethod
    def get_config(db: Session, project_id: int) -> PerturbationConfigOut:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise ValidationError("项目不存在")

        cfg = db.query(models.PerturbationConfig).filter(
            models.PerturbationConfig.project_id == project_id
        ).first()
        if not cfg:
            cfg = models.PerturbationConfig(project_id=project_id)
            db.add(cfg)
            db.commit()
            db.refresh(cfg)

        return PerturbationConfigOut.model_validate(cfg)

    @staticmethod
    def update_config(
        db: Session, project_id: int, data: PerturbationConfigUpdate
    ) -> PerturbationConfigOut:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise ValidationError("项目不存在")

        cfg = db.query(models.PerturbationConfig).filter(
            models.PerturbationConfig.project_id == project_id
        ).first()
        if not cfg:
            cfg = models.PerturbationConfig(project_id=project_id)
            db.add(cfg)
            db.flush()

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)

        db.commit()
        db.refresh(cfg)
        return PerturbationConfigOut.model_validate(cfg)

    @staticmethod
    def _generate_scenario_params(
        cfg: models.PerturbationConfig, idx: int, total: int
    ) -> Dict:
        params = {}
        if cfg.temperature_enabled:
            params["temperature"] = round(
                random.uniform(cfg.temperature_min, cfg.temperature_max), 2
            )
        else:
            params["temperature"] = cfg.temperature_baseline

        if cfg.viscosity_enabled:
            params["viscosity"] = round(
                random.uniform(cfg.viscosity_min, cfg.viscosity_max), 3
            )
        else:
            params["viscosity"] = cfg.viscosity_baseline

        if cfg.inflow_fluctuation_enabled:
            params["inflow_amplitude"] = round(
                random.uniform(0, cfg.inflow_fluctuation_amplitude), 3
            )
            params["inflow_frequency"] = cfg.inflow_fluctuation_frequency
        else:
            params["inflow_amplitude"] = 0.0
            params["inflow_frequency"] = 0.0

        if cfg.orifice_wear_enabled:
            params["orifice_wear"] = round(
                random.uniform(0, cfg.orifice_wear_max), 3
            )
        else:
            params["orifice_wear"] = 0.0

        if cfg.tilt_enabled:
            params["tilt_angle"] = round(
                random.uniform(cfg.tilt_angle_min, cfg.tilt_angle_max), 2
            )
        else:
            params["tilt_angle"] = cfg.tilt_angle_baseline

        params["baseline_temperature"] = cfg.temperature_baseline
        return params

    @staticmethod
    def _scenario_name(idx: int, params: Dict) -> str:
        parts = [f"场景#{idx+1}"]
        if params.get("temperature", 20) != 20:
            parts.append(f"{params['temperature']}°C")
        if params.get("viscosity", 1.0) != 1.0:
            parts.append(f"黏度x{params['viscosity']}")
        if params.get("inflow_amplitude", 0) > 0:
            parts.append(f"注水±{int(params['inflow_amplitude']*100)}%")
        if params.get("orifice_wear", 0) > 0:
            parts.append(f"磨损{int(params['orifice_wear']*100)}%")
        if params.get("tilt_angle", 0) > 0:
            parts.append(f"倾斜{params['tilt_angle']}°")
        return " ".join(parts) if len(parts) > 1 else f"场景#{idx+1} 基准"

    @staticmethod
    def _scenario_failed(results: List[Dict], threshold: float = 5.0) -> bool:
        if not results:
            return True
        errors = [abs(r.get("time_error") or 0) for r in results if r.get("time_error") is not None]
        if not errors:
            return False
        if max(errors) > threshold * 3:
            return True
        last_level = results[-1]["water_level"]
        return last_level <= 0

    @staticmethod
    def run_batch_simulation(
        db: Session,
        project_id: int,
        is_multi_vessel: bool = False,
        scenario_count: Optional[int] = None,
    ) -> BatchSimulationOut:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise ValidationError("项目不存在")

        cfg = RobustnessService.get_config(db, project_id)
        cfg_model = db.query(models.PerturbationConfig).filter(
            models.PerturbationConfig.project_id == project_id
        ).first()

        n_scenarios = scenario_count or cfg.scenario_count
        duration = cfg.simulation_duration
        time_step = cfg.time_step

        errors = []
        if cfg_model.temperature_min > cfg_model.temperature_max:
            errors.append(f"温度最小值 ({cfg_model.temperature_min}) 大于最大值 ({cfg_model.temperature_max})")
        if cfg_model.temperature_baseline < cfg_model.temperature_min or cfg_model.temperature_baseline > cfg_model.temperature_max:
            errors.append(f"温度基准值 ({cfg_model.temperature_baseline}) 超出范围 [{cfg_model.temperature_min}, {cfg_model.temperature_max}]")
        if cfg_model.viscosity_min > cfg_model.viscosity_max:
            errors.append(f"黏度最小值 ({cfg_model.viscosity_min}) 大于最大值 ({cfg_model.viscosity_max})")
        if cfg_model.viscosity_baseline < cfg_model.viscosity_min or cfg_model.viscosity_baseline > cfg_model.viscosity_max:
            errors.append(f"黏度基准值 ({cfg_model.viscosity_baseline}) 超出范围 [{cfg_model.viscosity_min}, {cfg_model.viscosity_max}]")
        if cfg_model.tilt_angle_min > cfg_model.tilt_angle_max:
            errors.append(f"倾斜角最小值 ({cfg_model.tilt_angle_min}) 大于最大值 ({cfg_model.tilt_angle_max})")
        if cfg_model.tilt_angle_baseline < cfg_model.tilt_angle_min or cfg_model.tilt_angle_baseline > cfg_model.tilt_angle_max:
            errors.append(f"倾斜角基准值 ({cfg_model.tilt_angle_baseline}) 超出范围 [{cfg_model.tilt_angle_min}, {cfg_model.tilt_angle_max}]")
        if time_step > duration:
            errors.append(f"时间步长 ({time_step}) 大于模拟时长 ({duration})")
        if errors:
            raise ValidationError("扰动配置无效：" + "; ".join(errors))

        if is_multi_vessel:
            vessels = db.query(models.Vessel).filter(
                models.Vessel.project_id == project_id
            ).order_by(models.Vessel.level_index).all()
            if not vessels:
                raise ValidationError("请先配置多级容器结构")
            relations = db.query(models.VesselFlowRelation).filter(
                models.VesselFlowRelation.project_id == project_id
            ).all()
            vessel_marks = {}
            for v in vessels:
                scheme = db.query(models.ScaleScheme).filter(
                    models.ScaleScheme.vessel_id == v.id
                ).first()
                vessel_marks[v.id] = sorted(scheme.marks, key=lambda m: m.target_time) if scheme else []
        else:
            config_model = db.query(models.ClepsydraConfig).filter(
                models.ClepsydraConfig.project_id == project_id
            ).first()
            if not config_model:
                raise ValidationError("请先配置漏壶结构参数")
            scheme = db.query(models.ScaleScheme).filter(
                models.ScaleScheme.project_id == project_id,
                models.ScaleScheme.vessel_id.is_(None),
            ).first()
            marks = sorted(scheme.marks, key=lambda m: m.target_time) if scheme else []

        db.query(models.SimulationScenario).filter(
            models.SimulationScenario.project_id == project_id,
            models.SimulationScenario.is_multi_vessel == is_multi_vessel,
        ).delete()
        db.commit()

        completed = 0
        all_scenario_summaries = []
        all_errors_by_param: Dict[str, List[Tuple[float, float]]] = {
            "temperature": [], "viscosity": [], "inflow_amplitude": [],
            "orifice_wear": [], "tilt_angle": [],
        }

        for idx in range(n_scenarios):
            params = RobustnessService._generate_scenario_params(cfg_model, idx, n_scenarios)
            name = RobustnessService._scenario_name(idx, params)

            scenario = models.SimulationScenario(
                project_id=project_id,
                config_id=cfg_model.id,
                scenario_index=idx + 1,
                name=name,
                is_multi_vessel=is_multi_vessel,
                status="running",
                temperature=params["temperature"],
                viscosity=params["viscosity"],
                inflow_amplitude=params["inflow_amplitude"],
                orifice_wear=params["orifice_wear"],
                tilt_angle=params["tilt_angle"],
                params=params,
            )
            db.add(scenario)
            db.flush()

            if is_multi_vessel:
                results_by_vessel = PerturbationPhysics.simulate_multi_vessel(
                    vessels, relations, vessel_marks, params, duration, time_step
                )
                all_errors = []
                for v in vessels:
                    v_results = results_by_vessel.get(v.id, [])
                    for r in v_results:
                        db.add(models.SimulationResult(
                            scenario_id=scenario.id,
                            vessel_id=v.id,
                            vessel_name=v.name,
                            time_point=r["time_point"],
                            water_level=r["water_level"],
                            expected_level=r["expected_level"],
                            flow_rate=r["flow_rate"],
                            inflow_rate=r["inflow_rate"],
                            time_error=r["time_error"],
                            level_error=r["level_error"],
                        ))
                        if r.get("time_error") is not None:
                            all_errors.append(abs(r["time_error"]))
            else:
                sim_results = PerturbationPhysics.simulate_single_vessel(
                    config_model.capacity, config_model.outlet_diameter,
                    config_model.target_duration, marks, params, duration, time_step,
                )
                all_errors = []
                for r in sim_results:
                    db.add(models.SimulationResult(
                        scenario_id=scenario.id,
                        time_point=r["time_point"],
                        water_level=r["water_level"],
                        expected_level=r["expected_level"],
                        flow_rate=r["flow_rate"],
                        inflow_rate=r["inflow_rate"],
                        time_error=r["time_error"],
                        level_error=r["level_error"],
                    ))
                    if r.get("time_error") is not None:
                        all_errors.append(abs(r["time_error"]))

            avg_err = sum(all_errors) / len(all_errors) if all_errors else 0
            max_err = max(all_errors) if all_errors else 0
            last_result = None
            if is_multi_vessel:
                bottom_v = max(vessels, key=lambda v: v.level_index) if vessels else None
                if bottom_v:
                    v_res = results_by_vessel.get(bottom_v.id, [])
                    last_result = v_res[-1] if v_res else None
            else:
                last_result = sim_results[-1] if sim_results else None
            _fle = last_result.get("level_error") if last_result else None
            final_level_err = float(_fle) if _fle is not None else 0.0
            failed = RobustnessService._scenario_failed(
                results_by_vessel[bottom_v.id] if (is_multi_vessel and bottom_v) else sim_results
            ) if is_multi_vessel else RobustnessService._scenario_failed(sim_results)

            all_scenario_summaries.append({
                "scenario_id": scenario.id,
                "scenario_index": idx + 1,
                "name": name,
                "avg_error": round(avg_err, 4),
                "max_error": round(max_err, 4),
                "final_level_error": round(final_level_err, 4),
                "failed": failed,
                "params": params,
            })

            for pname in ["temperature", "viscosity", "inflow_amplitude", "orifice_wear", "tilt_angle"]:
                all_errors_by_param[pname].append((params.get(pname, 0), avg_err))

            scenario.status = "completed"
            scenario.completed_at = datetime.utcnow()
            completed += 1

        db.flush()

        assessment = RobustnessService._compute_assessment(
            db, project_id, cfg_model.id, is_multi_vessel,
            all_scenario_summaries, all_errors_by_param,
        )

        db.commit()

        return BatchSimulationOut(
            ok=True,
            total_scenarios=n_scenarios,
            completed=completed,
            assessment_id=assessment.id if assessment else None,
            message=f"已完成 {completed}/{n_scenarios} 个模拟场景",
        )

    @staticmethod
    def _compute_assessment(
        db: Session,
        project_id: int,
        config_id: Optional[int],
        is_multi_vessel: bool,
        scenario_summaries: List[Dict],
        errors_by_param: Dict[str, List[Tuple[float, float]]],
    ) -> models.RobustnessAssessment:
        db.query(models.RobustnessAssessment).filter(
            models.RobustnessAssessment.project_id == project_id,
            models.RobustnessAssessment.is_multi_vessel == is_multi_vessel,
        ).delete()

        avg_errors = [s["avg_error"] for s in scenario_summaries]
        max_errors = [s["max_error"] for s in scenario_summaries]
        failed_count = sum(1 for s in scenario_summaries if s["failed"])

        overall_avg = sum(avg_errors) / len(avg_errors) if avg_errors else 0
        overall_max = max(max_errors) if max_errors else 0
        error_std = 0.0
        if len(avg_errors) > 1:
            mean = overall_avg
            variance = sum((e - mean) ** 2 for e in avg_errors) / len(avg_errors)
            error_std = math.sqrt(variance)
        failure_rate = failed_count / len(scenario_summaries) if scenario_summaries else 0

        stability_score = max(0.0, 100.0 - overall_avg * 3 - error_std * 5 - failure_rate * 50)
        stability_score = round(min(100.0, stability_score), 2)

        sensitivity_scores = []
        param_values = {}
        for pname, pairs in errors_by_param.items():
            if not pairs:
                continue
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            n = len(xs)
            if n < 2:
                continue
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            cov_xy = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n)) / n
            var_x = sum((x - mean_x) ** 2 for x in xs) / n
            var_y = sum((y - mean_y) ** 2 for y in ys) / n
            if var_x > 0 and var_y > 0:
                correlation = cov_xy / math.sqrt(var_x * var_y)
            else:
                correlation = 0.0
            score = abs(correlation) * 100
            direction = "正向" if correlation > 0 else "负向"

            param_min = min(xs)
            param_max = max(xs)
            param_range = param_max - param_min
            if param_range > 0 and mean_y > 0:
                y_min = min(ys)
                y_max = max(ys)
                sensitivity = (y_max - y_min) / mean_y / max(param_range, 1e-6) * 100
                score = max(score, min(100, sensitivity))

            sensitivity_scores.append({
                "parameter": pname,
                "parameter_label": PARAM_LABELS.get(pname, pname),
                "score": round(score, 2),
                "correlation": round(correlation, 4),
                "impact_direction": direction,
            })
            param_values[pname] = {"xs": xs, "ys": ys}

        sensitivity_scores.sort(key=lambda s: s["score"], reverse=True)

        parameter_ranking = []
        for rank, ss in enumerate(sensitivity_scores, 1):
            parameter_ranking.append({
                "rank": rank,
                "parameter": ss["parameter"],
                "parameter_label": ss["parameter_label"],
                "sensitivity_score": ss["score"],
                "category": PARAM_CATEGORIES.get(ss["parameter"], "其他"),
                "description": PARAM_DESCRIPTIONS.get(ss["parameter"], ""),
            })

        calibration_advice = []
        for pr in parameter_ranking:
            pname = pr["parameter"]
            score = pr["sensitivity_score"]
            if score < 15:
                continue
            if score >= 50:
                priority = "high"
            elif score >= 25:
                priority = "medium"
            else:
                priority = "low"

            pv = param_values.get(pname, {})
            xs = pv.get("xs", [])
            ys = pv.get("ys", [])

            if pname == "temperature":
                action = "加装恒温控制或保温层，将温度维持在 18-25°C"
                target_range = "18-25°C"
                reason = f"温度敏感度 {score:.1f}，建议采用水浴恒温或环境温控"
            elif pname == "viscosity":
                action = "使用纯净水，定期更换水体，避免杂质和微生物滋生"
                target_range = "0.9-1.1 mPa·s"
                reason = f"黏度敏感度 {score:.1f}，水体纯净度直接影响计时精度"
            elif pname == "inflow_amplitude":
                action = "增设恒压水箱或溢流稳压装置，稳定进水流量"
                target_range = "波动幅度 < 5%"
                reason = f"注水波动敏感度 {score:.1f}，建议增加上壶容量或采用恒压供水"
            elif pname == "orifice_wear":
                action = "出水嘴采用耐磨材料（如红宝石或玛瑙），定期校准孔径"
                target_range = "年磨损率 < 5%"
                reason = f"孔径磨损敏感度 {score:.1f}，材质选择和定期维护至关重要"
            elif pname == "tilt_angle":
                action = "安装调平底座和水平仪，定期校准容器水平度"
                target_range = "倾斜角 < 0.5°"
                reason = f"容器倾斜敏感度 {score:.1f}，机械结构稳定性是基础保障"
            else:
                action = "进一步分析该参数影响"
                target_range = "视情况而定"
                reason = f"该参数敏感度 {score:.1f}"

            expected_improvement = round(score * 0.4, 2)
            calibration_advice.append({
                "parameter": pname,
                "parameter_label": PARAM_LABELS.get(pname, pname),
                "priority": priority,
                "action": action,
                "target_range": target_range,
                "expected_improvement": expected_improvement,
                "reason": reason,
            })

        if stability_score >= 85:
            grade = "优秀"
            summary_text = f"系统稳健性评估为{grade}（综合评分 {stability_score}）。在当前扰动范围内系统表现稳定，平均误差 {overall_avg:.2f}%，故障率 {failure_rate*100:.1f}%。"
        elif stability_score >= 70:
            grade = "良好"
            summary_text = f"系统稳健性评估为{grade}（综合评分 {stability_score}）。大部分场景下运行可靠，建议对高敏感参数进行针对性校准。"
        elif stability_score >= 50:
            grade = "一般"
            summary_text = f"系统稳健性评估为{grade}（综合评分 {stability_score}）。环境扰动对计时精度影响较明显，建议优先落实高优先级校准措施。"
        else:
            grade = "较差"
            summary_text = f"系统稳健性评估为{grade}（综合评分 {stability_score}）。当前配置对环境变化过于敏感，必须进行系统性改进和校准后方可投入使用。"

        if sensitivity_scores:
            top_params = "、".join(s["parameter_label"] for s in sensitivity_scores[:3])
            summary_text += f" 影响最大的前三个参数：{top_params}。"

        assessment = models.RobustnessAssessment(
            project_id=project_id,
            config_id=config_id,
            is_multi_vessel=is_multi_vessel,
            overall_stability_score=stability_score,
            avg_error=round(overall_avg, 4),
            max_error=round(overall_max, 4),
            error_std=round(error_std, 4),
            failure_rate=round(failure_rate, 4),
            sensitivity_scores=[s.model_dump() if hasattr(s, 'model_dump') else s for s in sensitivity_scores],
            parameter_ranking=[p.model_dump() if hasattr(p, 'model_dump') else p for p in parameter_ranking],
            calibration_advice=[a.model_dump() if hasattr(a, 'model_dump') else a for a in calibration_advice],
            summary=summary_text,
        )
        db.add(assessment)
        db.flush()
        db.refresh(assessment)

        if hasattr(assessment, 'scenario_summaries'):
            assessment.scenario_summaries = scenario_summaries

        return assessment

    @staticmethod
    def list_scenarios(
        db: Session, project_id: int, is_multi_vessel: bool = False
    ) -> List[SimulationScenarioOut]:
        scenarios = db.query(models.SimulationScenario).filter(
            models.SimulationScenario.project_id == project_id,
            models.SimulationScenario.is_multi_vessel == is_multi_vessel,
        ).order_by(models.SimulationScenario.scenario_index).all()
        return [SimulationScenarioOut.model_validate(s) for s in scenarios]

    @staticmethod
    def get_scenario_detail(
        db: Session, scenario_id: int
    ) -> SimulationScenarioDetail:
        scenario = db.query(models.SimulationScenario).filter(
            models.SimulationScenario.id == scenario_id
        ).first()
        if not scenario:
            raise ValidationError("模拟场景不存在")

        results = db.query(models.SimulationResult).filter(
            models.SimulationResult.scenario_id == scenario_id
        ).order_by(models.SimulationResult.time_point).all()

        if scenario.is_multi_vessel:
            vessel_results: Dict[str, List[SimulationResultPoint]] = {}
            for r in results:
                key = r.vessel_name or f"vessel_{r.vessel_id}"
                if key not in vessel_results:
                    vessel_results[key] = []
                vessel_results[key].append(SimulationResultPoint(
                    time_point=r.time_point,
                    water_level=r.water_level,
                    expected_level=r.expected_level,
                    flow_rate=r.flow_rate,
                    inflow_rate=r.inflow_rate,
                    time_error=r.time_error,
                    level_error=r.level_error,
                ))
            return SimulationScenarioDetail(
                scenario=SimulationScenarioOut.model_validate(scenario),
                results=[],
                vessel_results=vessel_results,
            )
        else:
            points = [
                SimulationResultPoint(
                    time_point=r.time_point,
                    water_level=r.water_level,
                    expected_level=r.expected_level,
                    flow_rate=r.flow_rate,
                    inflow_rate=r.inflow_rate,
                    time_error=r.time_error,
                    level_error=r.level_error,
                )
                for r in results
            ]
            return SimulationScenarioDetail(
                scenario=SimulationScenarioOut.model_validate(scenario),
                results=points,
            )

    @staticmethod
    def get_assessment(
        db: Session, project_id: int, is_multi_vessel: bool = False
    ) -> Optional[RobustnessAssessmentOut]:
        assessment = db.query(models.RobustnessAssessment).filter(
            models.RobustnessAssessment.project_id == project_id,
            models.RobustnessAssessment.is_multi_vessel == is_multi_vessel,
        ).order_by(models.RobustnessAssessment.created_at.desc()).first()
        if not assessment:
            return None

        scenarios = db.query(models.SimulationScenario).filter(
            models.SimulationScenario.project_id == project_id,
            models.SimulationScenario.is_multi_vessel == is_multi_vessel,
        ).all()

        scenario_summaries = []
        for s in scenarios:
            results = db.query(models.SimulationResult).filter(
                models.SimulationResult.scenario_id == s.id
            ).all()
            errors = [abs(r.time_error) for r in results if r.time_error is not None]
            avg_err = sum(errors) / len(errors) if errors else 0
            max_err = max(errors) if errors else 0
            last = results[-1] if results else None
            scenario_summaries.append(ScenarioSummary(
                scenario_id=s.id,
                scenario_index=s.scenario_index,
                name=s.name,
                avg_error=round(avg_err, 4),
                max_error=round(max_err, 4),
                final_level_error=round(last.level_error, 4) if last and last.level_error else 0,
                failed=RobustnessService._scenario_failed([{"time_error": r.time_error} for r in results]),
                params=s.params or {},
            ))

        sens_scores = [
            SensitivityScore(**s) if isinstance(s, dict) else s
            for s in (assessment.sensitivity_scores or [])
        ]
        param_ranking = [
            ParameterRanking(**p) if isinstance(p, dict) else p
            for p in (assessment.parameter_ranking or [])
        ]
        cal_advice = [
            CalibrationAdvice(**a) if isinstance(a, dict) else a
            for a in (assessment.calibration_advice or [])
        ]

        return RobustnessAssessmentOut(
            id=assessment.id,
            project_id=assessment.project_id,
            config_id=assessment.config_id,
            is_multi_vessel=assessment.is_multi_vessel,
            created_at=assessment.created_at,
            overall_stability_score=assessment.overall_stability_score,
            avg_error=assessment.avg_error,
            max_error=assessment.max_error,
            error_std=assessment.error_std,
            failure_rate=assessment.failure_rate,
            sensitivity_scores=sens_scores,
            parameter_ranking=param_ranking,
            calibration_advice=cal_advice,
            scenario_summaries=scenario_summaries,
            summary=assessment.summary,
        )
