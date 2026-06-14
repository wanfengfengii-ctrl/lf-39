from __future__ import annotations

import math
import random
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any

from sqlalchemy.orm import Session

from database import models
from schemas import (
    InversionRunRequest, JointInversionOut, InversionListOut,
    ConfidenceInterval, InversionCandidate, ConvergencePoint,
    AlignedDataPoint, InversionCalibrationAdvice,
)
from services.robustness_service import PerturbationPhysics
from services.validation_service import ValidationError


PARAM_LABELS = {
    "temperature": "环境温度",
    "viscosity": "液体黏度",
    "inflow_amplitude": "注水波动幅度",
    "orifice_wear": "孔径磨损程度",
    "tilt_angle": "容器倾斜角度",
}

PARAM_UNITS = {
    "temperature": "°C",
    "viscosity": "mPa·s",
    "inflow_amplitude": "",
    "orifice_wear": "",
    "tilt_angle": "°",
}

PARAM_CATEGORIES = {
    "temperature": "环境因素",
    "viscosity": "物理参数",
    "inflow_amplitude": "供水系统",
    "orifice_wear": "器件老化",
    "tilt_angle": "机械结构",
}

BASELINE_VALUES = {
    "temperature": 20.0,
    "viscosity": 1.0,
    "inflow_amplitude": 0.0,
    "orifice_wear": 0.0,
    "tilt_angle": 0.0,
}

IDEAL_RANGES = {
    "temperature": (18.0, 25.0),
    "viscosity": (0.95, 1.05),
    "inflow_amplitude": (0.0, 0.05),
    "orifice_wear": (0.0, 0.05),
    "tilt_angle": (0.0, 0.5),
}


def _lerp(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    if abs(x1 - x0) < 1e-12:
        return y0
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)


def _interpolate_level(time_points: List[float], levels: List[float], t: float) -> float:
    if not time_points or not levels:
        return 0.0
    if t <= time_points[0]:
        return levels[0]
    if t >= time_points[-1]:
        return levels[-1]
    for i in range(len(time_points) - 1):
        if time_points[i] <= t <= time_points[i + 1]:
            return _lerp(t, time_points[i], levels[i], time_points[i + 1], levels[i + 1])
    return levels[-1]


def _compute_r2(actual: List[float], predicted: List[float]) -> float:
    n = len(actual)
    if n < 2:
        return 0.0
    mean_actual = sum(actual) / n
    ss_tot = sum((a - mean_actual) ** 2 for a in actual)
    ss_res = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    if ss_tot < 1e-12:
        return 1.0 if ss_res < 1e-12 else 0.0
    return 1.0 - ss_res / ss_tot


def _compute_fit_metrics(
    aligned_points: List[Tuple[float, float, float]]
) -> Tuple[float, float, float, float, float, float]:
    errors_pct = []
    errors_abs = []
    actual_levels = []
    sim_levels = []
    for t, exp_lvl, sim_lvl in aligned_points:
        actual_levels.append(exp_lvl)
        sim_levels.append(sim_lvl)
        diff = sim_lvl - exp_lvl
        errors_abs.append(abs(diff))
        if exp_lvl > 0:
            errors_pct.append(abs(diff) / exp_lvl * 100.0)
        else:
            errors_pct.append(0.0)

    n = len(aligned_points)
    best_fit_err = max(errors_pct) if errors_pct else 0.0
    avg_fit_err = sum(errors_pct) / n if n > 0 else 0.0
    err_std = 0.0
    if n > 1:
        variance = sum((e - avg_fit_err) ** 2 for e in errors_pct) / n
        err_std = math.sqrt(variance)
    rmse = math.sqrt(sum((a - p) ** 2 for a, p in zip(actual_levels, sim_levels)) / n) if n > 0 else 0.0
    r2 = _compute_r2(actual_levels, sim_levels)
    mae = sum(errors_abs) / n if n > 0 else 0.0
    return best_fit_err, avg_fit_err, err_std, rmse, r2, mae


class InversionObjective:
    def __init__(
        self,
        db: Session,
        project_id: int,
        experiment_records: List,
        is_multi_vessel: bool,
        target_vessel_id: Optional[int] = None,
    ):
        self.db = db
        self.project_id = project_id
        self.is_multi_vessel = is_multi_vessel
        self.target_vessel_id = target_vessel_id

        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise ValidationError("项目不存在")

        if is_multi_vessel:
            self.vessels = db.query(models.Vessel).filter(
                models.Vessel.project_id == project_id
            ).order_by(models.Vessel.level_index).all()
            self.relations = db.query(models.VesselFlowRelation).filter(
                models.VesselFlowRelation.project_id == project_id
            ).all()
            self.vessel_marks = {}
            for v in self.vessels:
                scheme = db.query(models.ScaleScheme).filter(
                    models.ScaleScheme.vessel_id == v.id
                ).first()
                self.vessel_marks[v.id] = sorted(
                    scheme.marks, key=lambda m: m.target_time
                ) if scheme else []

            if target_vessel_id is None and self.vessels:
                target_vessel = max(self.vessels, key=lambda v: v.level_index)
                self.target_vessel_id = target_vessel.id

            target_records = [
                r for r in experiment_records
                if getattr(r, 'vessel_id', None) == self.target_vessel_id
            ]
            target_records.sort(key=lambda r: r.time_point)
            self.exp_times = [r.time_point for r in target_records]
            self.exp_levels = [r.water_level for r in target_records]
        else:
            self.config_model = db.query(models.ClepsydraConfig).filter(
                models.ClepsydraConfig.project_id == project_id
            ).first()
            if not self.config_model:
                raise ValidationError("请先配置漏壶结构参数")
            scheme = db.query(models.ScaleScheme).filter(
                models.ScaleScheme.project_id == project_id,
                models.ScaleScheme.vessel_id.is_(None),
            ).first()
            self.marks = sorted(scheme.marks, key=lambda m: m.target_time) if scheme else []

            records = sorted(experiment_records, key=lambda r: r.time_point)
            self.exp_times = [r.time_point for r in records]
            self.exp_levels = [r.water_level for r in records]

        if not self.exp_times:
            raise ValidationError("实验数据为空，无法进行反演")

        self.duration = max(self.exp_times) if self.exp_times else 60.0
        self.time_step = max(0.1, min(1.0, self.duration / 100.0))

    def evaluate(self, params: Dict[str, float]) -> Tuple[float, List[Tuple[float, float, float]]]:
        perturbation_params = dict(params)
        perturbation_params["baseline_temperature"] = 20.0
        if "inflow_frequency" not in perturbation_params:
            perturbation_params["inflow_frequency"] = 0.5

        if self.is_multi_vessel:
            results_by_vessel = PerturbationPhysics.simulate_multi_vessel(
                self.vessels, self.relations, self.vessel_marks,
                perturbation_params, self.duration, self.time_step,
            )
            target_results = results_by_vessel.get(self.target_vessel_id, [])
        else:
            target_results = PerturbationPhysics.simulate_single_vessel(
                self.config_model.capacity, self.config_model.outlet_diameter,
                self.config_model.target_duration, self.marks,
                perturbation_params, self.duration, self.time_step,
            )

        sim_times = [r["time_point"] for r in target_results]
        sim_levels = [r["water_level"] for r in target_results]

        aligned = []
        for t, exp_lvl in zip(self.exp_times, self.exp_levels):
            sim_lvl = _interpolate_level(sim_times, sim_levels, t)
            aligned.append((t, exp_lvl, sim_lvl))

        _, avg_err, _, rmse, _, _ = _compute_fit_metrics(aligned)
        objective = rmse * 0.6 + avg_err * 0.4

        return objective, aligned


class ParticleSwarmOptimizer:
    def __init__(
        self,
        objective_func,
        param_ranges: Dict[str, Tuple[float, float]],
        particle_count: int = 30,
        max_iterations: int = 50,
        inertia_weight: float = 0.7,
        cognitive_weight: float = 1.5,
        social_weight: float = 1.5,
    ):
        self.objective_func = objective_func
        self.param_names = list(param_ranges.keys())
        self.param_ranges = param_ranges
        self.n_particles = particle_count
        self.max_iter = max_iterations
        self.w = inertia_weight
        self.c1 = cognitive_weight
        self.c2 = social_weight

        self.particles: List[Dict[str, float]] = []
        self.velocities: List[Dict[str, float]] = []
        self.personal_best: List[Dict[str, float]] = []
        self.personal_best_scores: List[float] = []
        self.global_best: Optional[Dict[str, float]] = None
        self.global_best_score: float = float('inf')
        self.convergence_history: List[Dict[str, Any]] = []
        self.all_evaluations: List[Tuple[Dict[str, float], float]] = []

    def _init_particles(self):
        for _ in range(self.n_particles):
            pos = {}
            vel = {}
            for name, (lo, hi) in self.param_ranges.items():
                pos[name] = random.uniform(lo, hi)
                vel[name] = random.uniform(-(hi - lo) * 0.1, (hi - lo) * 0.1)
            self.particles.append(pos)
            self.velocities.append(vel)
            self.personal_best.append(dict(pos))
            self.personal_best_scores.append(float('inf'))

    def _clip_position(self, pos: Dict[str, float]) -> Dict[str, float]:
        clipped = {}
        for name, (lo, hi) in self.param_ranges.items():
            clipped[name] = max(lo, min(hi, pos[name]))
        return clipped

    def optimize(self) -> Tuple[Dict[str, float], float]:
        self._init_particles()

        for iteration in range(self.max_iter):
            for i in range(self.n_particles):
                pos = self.particles[i]
                score, _ = self.objective_func(pos)
                self.all_evaluations.append((dict(pos), score))

                if score < self.personal_best_scores[i]:
                    self.personal_best_scores[i] = score
                    self.personal_best[i] = dict(pos)

                if score < self.global_best_score:
                    self.global_best_score = score
                    self.global_best = dict(pos)

            for i in range(self.n_particles):
                for name in self.param_names:
                    r1 = random.random()
                    r2 = random.random()
                    cognitive = self.c1 * r1 * (self.personal_best[i][name] - self.particles[i][name])
                    social = self.c2 * r2 * ((self.global_best or {name: 0})[name] - self.particles[i][name])
                    self.velocities[i][name] = (
                        self.w * self.velocities[i][name] + cognitive + social
                    )
                    self.particles[i][name] += self.velocities[i][name]
                self.particles[i] = self._clip_position(self.particles[i])

            iteration_best = min(
                self.personal_best_scores
            ) if self.personal_best_scores else float('inf')
            iteration_avg = (
                sum(self.personal_best_scores) / len(self.personal_best_scores)
                if self.personal_best_scores else float('inf')
            )
            self.convergence_history.append({
                "iteration": iteration + 1,
                "best_error": round(iteration_best, 6),
                "avg_error": round(iteration_avg, 6),
                "best_params": {k: round(v, 6) for k, v in (self.global_best or {}).items()},
            })

        return self.global_best or {}, self.global_best_score


class GridSearchRefiner:
    def __init__(self, objective_func, param_ranges: Dict[str, Tuple[float, float]], density: int = 5):
        self.objective_func = objective_func
        self.param_names = list(param_ranges.keys())
        self.param_ranges = param_ranges
        self.density = density

    def refine(self, center: Dict[str, float], shrink_factor: float = 0.3) -> Tuple[Dict[str, float], float, List[Tuple[Dict[str, float], float]]]:
        local_ranges = {}
        for name, (lo, hi) in self.param_ranges.items():
            c = center.get(name, (lo + hi) / 2)
            half_span = (hi - lo) * shrink_factor / 2
            local_ranges[name] = (max(lo, c - half_span), min(hi, c + half_span))

        grid_points = self._generate_grid(local_ranges)

        results = []
        best_score = float('inf')
        best_params = dict(center)

        for point in grid_points:
            score, _ = self.objective_func(point)
            results.append((dict(point), score))
            if score < best_score:
                best_score = score
                best_params = dict(point)

        results.sort(key=lambda x: x[1])
        return best_params, best_score, results

    def _generate_grid(self, local_ranges: Dict[str, Tuple[float, float]]) -> List[Dict[str, float]]:
        axes = []
        for name in self.param_names:
            lo, hi = local_ranges[name]
            axis = [lo + i * (hi - lo) / (self.density - 1) for i in range(self.density)]
            axes.append((name, axis))

        def _combine(idx: int, current: Dict[str, float]) -> List[Dict[str, float]]:
            if idx >= len(axes):
                return [dict(current)]
            name, axis = axes[idx]
            results = []
            for val in axis:
                current[name] = val
                results.extend(_combine(idx + 1, current))
            return results

        return _combine(0, {})


class BootstrapConfidence:
    def __init__(self, objective_func, param_ranges: Dict[str, Tuple[float, float]]):
        self.objective_func = objective_func
        self.param_names = list(param_ranges.keys())
        self.param_ranges = param_ranges

    def compute(
        self,
        optimal_params: Dict[str, float],
        n_bootstrap: int = 100,
        local_scale: float = 0.2,
    ) -> Dict[str, Tuple[float, float, float]]:
        samples = {name: [] for name in self.param_names}

        for _ in range(n_bootstrap):
            perturbed = {}
            for name, (lo, hi) in self.param_ranges.items():
                center = optimal_params.get(name, (lo + hi) / 2)
                sigma = (hi - lo) * local_scale
                sample = random.gauss(center, sigma)
                perturbed[name] = max(lo, min(hi, sample))

            score, _ = self.objective_func(perturbed)
            best_score, _ = self.objective_func(optimal_params)
            if score <= best_score * 2.0:
                for name in self.param_names:
                    samples[name].append(perturbed[name])

        intervals = {}
        for name in self.param_names:
            vals = sorted(samples[name])
            if len(vals) >= 10:
                lo_idx = int(len(vals) * 0.025)
                hi_idx = int(len(vals) * 0.975) - 1
                lo_idx = max(0, min(lo_idx, len(vals) - 1))
                hi_idx = max(0, min(hi_idx, len(vals) - 1))
                ci_low = vals[lo_idx]
                ci_high = vals[hi_idx]
            else:
                lo, hi = self.param_ranges[name]
                center = optimal_params.get(name, (lo + hi) / 2)
                span = (hi - lo) * 0.15
                ci_low = max(lo, center - span)
                ci_high = min(hi, center + span)
            intervals[name] = (ci_low, optimal_params.get(name, 0), ci_high)

        return intervals


class JointInversionService:

    @staticmethod
    def _get_default_ranges(
        db: Session, project_id: int
    ) -> Dict[str, Tuple[float, float, float, bool]]:
        cfg = db.query(models.PerturbationConfig).filter(
            models.PerturbationConfig.project_id == project_id
        ).first()
        if not cfg:
            cfg = models.PerturbationConfig(project_id=project_id)
            db.add(cfg)
            db.commit()
            db.refresh(cfg)

        return {
            "temperature": (
                cfg.temperature_min, cfg.temperature_max,
                cfg.temperature_baseline, cfg.temperature_enabled,
            ),
            "viscosity": (
                cfg.viscosity_min, cfg.viscosity_max,
                cfg.viscosity_baseline, cfg.viscosity_enabled,
            ),
            "inflow_amplitude": (
                0.0, cfg.inflow_fluctuation_amplitude,
                0.0, cfg.inflow_fluctuation_enabled,
            ),
            "orifice_wear": (
                0.0, cfg.orifice_wear_max,
                0.0, cfg.orifice_wear_enabled,
            ),
            "tilt_angle": (
                cfg.tilt_angle_min, cfg.tilt_angle_max,
                cfg.tilt_angle_baseline, cfg.tilt_enabled,
            ),
        }

    @staticmethod
    def _get_experiment_records(
        db: Session, project_id: int, experiment_id: Optional[int], is_multi_vessel: bool
    ) -> Tuple[List, int]:
        if experiment_id:
            exp = db.query(models.Experiment).filter(
                models.Experiment.id == experiment_id,
                models.Experiment.project_id == project_id,
            ).first()
            if not exp:
                raise ValidationError("指定的实验不存在")
        else:
            status_filter = ("finalized", "completed")
            exps = db.query(models.Experiment).filter(
                models.Experiment.project_id == project_id,
                models.Experiment.status.in_(status_filter),
                models.Experiment.is_multi_vessel == is_multi_vessel,
            ).order_by(models.Experiment.round_number.desc()).all()
            if not exps:
                raise ValidationError(
                    "没有已完成的实验数据，请先完成至少一轮实验后再进行反演"
                )
            exp = exps[0]

        if is_multi_vessel:
            records = list(exp.vessel_records)
        else:
            records = list(exp.records)

        return records, exp.id

    @staticmethod
    def list_results(db: Session, project_id: int) -> List[InversionListOut]:
        results = db.query(models.JointInversionResult).filter(
            models.JointInversionResult.project_id == project_id
        ).order_by(models.JointInversionResult.created_at.desc()).all()
        return [
            InversionListOut(
                id=r.id,
                project_id=r.project_id,
                experiment_id=r.experiment_id,
                is_multi_vessel=r.is_multi_vessel,
                status=r.status,
                created_at=r.created_at,
                completed_at=r.completed_at,
                algorithm=r.algorithm,
                best_fit_error=r.best_fit_error,
                r_squared=r.r_squared,
            )
            for r in results
        ]

    @staticmethod
    def run_inversion(
        db: Session,
        project_id: int,
        request: InversionRunRequest,
    ) -> JointInversionOut:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            raise ValidationError("项目不存在")

        try:
            records, exp_id = JointInversionService._get_experiment_records(
                db, project_id, request.experiment_id, request.is_multi_vessel
            )
        except ValidationError:
            raise

        default_ranges = JointInversionService._get_default_ranges(db, project_id)

        active_param_ranges: Dict[str, Tuple[float, float]] = {}
        if request.custom_ranges:
            for cr in request.custom_ranges:
                if cr.enabled:
                    active_param_ranges[cr.parameter] = (cr.min_value, cr.max_value)
        else:
            for name, (lo, hi, baseline, enabled) in default_ranges.items():
                if enabled:
                    active_param_ranges[name] = (lo, hi)

        if not active_param_ranges:
            raise ValidationError("至少需要启用一个扰动参数进行反演")

        objective = InversionObjective(
            db, project_id, records, request.is_multi_vessel, request.target_vessel_id
        )

        inversion_result = models.JointInversionResult(
            project_id=project_id,
            experiment_id=exp_id,
            is_multi_vessel=request.is_multi_vessel,
            status="running",
            algorithm=request.algorithm,
            particle_count=request.particle_count,
            iteration_count=request.iteration_count,
            grid_density=request.grid_density,
        )
        db.add(inversion_result)
        db.flush()

        algo = request.algorithm
        convergence_history_list = []

        if algo in ("pso", "hybrid_pso_grid"):
            pso = ParticleSwarmOptimizer(
                objective.evaluate,
                active_param_ranges,
                particle_count=request.particle_count,
                max_iterations=request.iteration_count,
            )
            optimal_params, pso_score = pso.optimize()
            convergence_history_list = pso.convergence_history
            all_evals = pso.all_evaluations
        else:
            optimal_params = {name: (lo + hi) / 2 for name, (lo, hi) in active_param_ranges.items()}
            all_evals = []

        if algo in ("grid_search", "hybrid_pso_grid"):
            gs = GridSearchRefiner(
                objective.evaluate, active_param_ranges, density=request.grid_density
            )
            shrink = 0.5 if algo == "grid_search" else 0.25
            optimal_params, gs_score, grid_results = gs.refine(optimal_params, shrink_factor=shrink)
            all_evals.extend(grid_results)

        if algo == "nelder_mead":
            optimal_params = JointInversionService._nelder_mead(
                objective.evaluate, optimal_params, active_param_ranges
            )

        for name in ["temperature", "viscosity", "inflow_amplitude", "orifice_wear", "tilt_angle"]:
            if name not in active_param_ranges:
                optimal_params[name] = BASELINE_VALUES[name]
                _, (lo, hi, baseline, _) = next(
                    ((k, v) for k, v in default_ranges.items() if k == name),
                    (name, (0, 1, BASELINE_VALUES[name], True))
                )

        final_score, aligned_data = objective.evaluate(optimal_params)
        best_fit_err, avg_fit_err, err_std, rmse, r2, mae = _compute_fit_metrics(aligned_data)

        bootstrap = BootstrapConfidence(objective.evaluate, {
            name: (
                default_ranges[name][0],
                default_ranges[name][1],
            )
            for name in ["temperature", "viscosity", "inflow_amplitude", "orifice_wear", "tilt_angle"]
            if name in default_ranges
        })
        ci_results = bootstrap.compute(optimal_params, n_bootstrap=80)

        ci_list = []
        for name, (ci_low, best, ci_high) in ci_results.items():
            ci_low_r = round(ci_low, 6)
            ci_high_r = round(ci_high, 6)
            best_r = round(best, 6)
            width_pct = 0.0
            if abs(best) > 1e-9:
                width_pct = round((ci_high - ci_low) / abs(best) * 100, 2)
            elif ci_high - ci_low > 0:
                width_pct = 100.0
            ci_list.append({
                "parameter": name,
                "parameter_label": PARAM_LABELS.get(name, name),
                "low": ci_low_r,
                "high": ci_high_r,
                "best": best_r,
                "unit": PARAM_UNITS.get(name),
                "width_percent": width_pct,
            })

        all_evals.sort(key=lambda x: x[1])
        top_candidates = []
        seen_sets = set()
        rank = 1
        for params, score in all_evals:
            key = tuple(round(params.get(k, 0), 4) for k in ["temperature", "viscosity", "inflow_amplitude", "orifice_wear", "tilt_angle"])
            if key in seen_sets:
                continue
            seen_sets.add(key)
            p = dict(params)
            for k in ["temperature", "viscosity", "inflow_amplitude", "orifice_wear", "tilt_angle"]:
                if k not in p:
                    p[k] = BASELINE_VALUES[k]
            _, rmse_val = JointInversionService._candidate_rmse(objective, p)
            top_candidates.append({
                "rank": rank,
                "temperature": round(p["temperature"], 4),
                "viscosity": round(p["viscosity"], 4),
                "inflow_amplitude": round(p["inflow_amplitude"], 4),
                "orifice_wear": round(p["orifice_wear"], 4),
                "tilt_angle": round(p["tilt_angle"], 4),
                "fit_error": round(score, 6),
                "rmse": round(rmse_val, 6),
            })
            rank += 1
            if rank > 10:
                break

        aligned_points = []
        sim_opt_points = []
        for t, exp_lvl, sim_lvl in aligned_data:
            diff = round(sim_lvl - exp_lvl, 4)
            err_pct = None
            if exp_lvl > 0:
                err_pct = round(diff / exp_lvl * 100, 4)
            aligned_points.append({
                "time_point": round(t, 4),
                "experiment_level": round(exp_lvl, 4),
                "simulated_level": round(sim_lvl, 4),
                "level_difference": diff,
                "error_percent": err_pct,
            })
            sim_opt_points.append({
                "time_point": round(t, 4),
                "water_level": round(sim_lvl, 4),
            })

        calibration_advice = JointInversionService._generate_calibration_advice(
            optimal_params, ci_results, r2, rmse
        )

        summary = JointInversionService._generate_summary(
            optimal_params, best_fit_err, avg_fit_err, rmse, r2, calibration_advice
        )

        inversion_result.status = "completed"
        inversion_result.completed_at = datetime.utcnow()
        inversion_result.optimal_temperature = round(optimal_params.get("temperature", 20.0), 6)
        inversion_result.optimal_viscosity = round(optimal_params.get("viscosity", 1.0), 6)
        inversion_result.optimal_inflow_amplitude = round(optimal_params.get("inflow_amplitude", 0.0), 6)
        inversion_result.optimal_orifice_wear = round(optimal_params.get("orifice_wear", 0.0), 6)
        inversion_result.optimal_tilt_angle = round(optimal_params.get("tilt_angle", 0.0), 6)
        inversion_result.optimal_params = {k: round(v, 6) for k, v in optimal_params.items()}
        inversion_result.best_fit_error = round(best_fit_err, 6)
        inversion_result.avg_fit_error = round(avg_fit_err, 6)
        inversion_result.error_std = round(err_std, 6)
        inversion_result.rmse = round(rmse, 6)
        inversion_result.r_squared = round(r2, 6)

        for ci in ci_list:
            pname = ci["parameter"]
            if pname == "temperature":
                inversion_result.temperature_ci_low = ci["low"]
                inversion_result.temperature_ci_high = ci["high"]
            elif pname == "viscosity":
                inversion_result.viscosity_ci_low = ci["low"]
                inversion_result.viscosity_ci_high = ci["high"]
            elif pname == "inflow_amplitude":
                inversion_result.inflow_amplitude_ci_low = ci["low"]
                inversion_result.inflow_amplitude_ci_high = ci["high"]
            elif pname == "orifice_wear":
                inversion_result.orifice_wear_ci_low = ci["low"]
                inversion_result.orifice_wear_ci_high = ci["high"]
            elif pname == "tilt_angle":
                inversion_result.tilt_angle_ci_low = ci["low"]
                inversion_result.tilt_angle_ci_high = ci["high"]

        inversion_result.confidence_intervals = ci_list
        inversion_result.top_candidates = top_candidates
        inversion_result.convergence_history = convergence_history_list
        inversion_result.aligned_experiment_points = aligned_points
        inversion_result.simulated_optimal_points = sim_opt_points
        inversion_result.calibration_advice = [a.model_dump() if hasattr(a, 'model_dump') else a for a in calibration_advice]
        inversion_result.summary = summary

        db.commit()
        db.refresh(inversion_result)

        return JointInversionService._to_out_model(inversion_result)

    @staticmethod
    def _candidate_rmse(objective, params: Dict[str, float]) -> Tuple[float, float]:
        score, aligned = objective.evaluate(params)
        _, _, _, rmse, _, _ = _compute_fit_metrics(aligned)
        return score, rmse

    @staticmethod
    def _nelder_mead(
        objective_func,
        start_params: Dict[str, float],
        param_ranges: Dict[str, Tuple[float, float]],
        max_iter: int = 200,
        tol: float = 1e-8,
    ) -> Dict[str, float]:
        names = list(param_ranges.keys())
        n = len(names)
        if n == 0:
            return start_params

        def to_vector(p: Dict[str, float]) -> List[float]:
            return [p[name] for name in names]

        def to_params(v: List[float]) -> Dict[str, float]:
            p = {}
            for i, name in enumerate(names):
                lo, hi = param_ranges[name]
                p[name] = max(lo, min(hi, v[i]))
            return p

        def score_vec(v: List[float]) -> float:
            s, _ = objective_func(to_params(v))
            return s

        simplex = []
        x0 = to_vector(start_params)
        simplex.append((x0, score_vec(x0)))

        for i in range(n):
            step = 0.1
            x = list(x0)
            lo, hi = param_ranges[names[i]]
            x[i] = min(hi, max(lo, x[i] + step * (hi - lo)))
            simplex.append((x, score_vec(x)))

        alpha = 1.0
        gamma = 2.0
        rho = 0.5
        sigma = 0.5

        for iteration in range(max_iter):
            simplex.sort(key=lambda x: x[1])
            best_score = simplex[0][1]
            worst_score = simplex[-1][1]

            if abs(worst_score - best_score) < tol:
                break

            centroid = [0.0] * n
            for i in range(n):
                centroid[i] = sum(simplex[j][0][i] for j in range(n)) / n

            xr = [centroid[i] + alpha * (centroid[i] - simplex[-1][0][i]) for i in range(n)]
            sr = score_vec(xr)

            if sr < simplex[0][1]:
                xe = [centroid[i] + gamma * (xr[i] - centroid[i]) for i in range(n)]
                se = score_vec(xe)
                if se < sr:
                    simplex[-1] = (xe, se)
                else:
                    simplex[-1] = (xr, sr)
            elif sr < simplex[-2][1]:
                simplex[-1] = (xr, sr)
            else:
                if sr < worst_score:
                    xc = [centroid[i] + rho * (xr[i] - centroid[i]) for i in range(n)]
                    sc = score_vec(xc)
                    if sc <= sr:
                        simplex[-1] = (xc, sc)
                    else:
                        best_vec = simplex[0][0]
                        for k in range(1, len(simplex)):
                            shrink = [
                                best_vec[i] + sigma * (simplex[k][0][i] - best_vec[i])
                                for i in range(n)
                            ]
                            simplex[k] = (shrink, score_vec(shrink))
                else:
                    xcc = [centroid[i] - rho * (centroid[i] - simplex[-1][0][i]) for i in range(n)]
                    scc = score_vec(xcc)
                    if scc < worst_score:
                        simplex[-1] = (xcc, scc)
                    else:
                        best_vec = simplex[0][0]
                        for k in range(1, len(simplex)):
                            shrink = [
                                best_vec[i] + sigma * (simplex[k][0][i] - best_vec[i])
                                for i in range(n)
                            ]
                            simplex[k] = (shrink, score_vec(shrink))

        simplex.sort(key=lambda x: x[1])
        return to_params(simplex[0][0])

    @staticmethod
    def _generate_calibration_advice(
        optimal_params: Dict[str, float],
        ci_results: Dict[str, Tuple[float, float, float]],
        r2: float,
        rmse: float,
    ) -> List[InversionCalibrationAdvice]:
        advice_list = []

        param_deviations = []
        for name in ["temperature", "viscosity", "inflow_amplitude", "orifice_wear", "tilt_angle"]:
            value = optimal_params.get(name, BASELINE_VALUES[name])
            ideal_lo, ideal_hi = IDEAL_RANGES[name]
            if value < ideal_lo:
                deviation = ideal_lo - value
            elif value > ideal_hi:
                deviation = value - ideal_hi
            else:
                deviation = 0.0
            range_span = ideal_hi - ideal_lo if ideal_hi > ideal_lo else 1.0
            severity = deviation / range_span if range_span > 0 else 0.0
            param_deviations.append((name, value, deviation, severity))

        param_deviations.sort(key=lambda x: x[3], reverse=True)

        for name, value, deviation, severity in param_deviations:
            if severity < 0.05 and name != "orifice_wear":
                continue

            if severity >= 0.8:
                priority = "high"
            elif severity >= 0.3:
                priority = "medium"
            else:
                priority = "low"

            ideal_lo, ideal_hi = IDEAL_RANGES[name]
            label = PARAM_LABELS[name]
            category = PARAM_CATEGORIES[name]
            unit = PARAM_UNITS.get(name, "")
            ci = ci_results.get(name, (value * 0.9, value, value * 1.1))

            if name == "temperature":
                if value < ideal_lo:
                    action = (
                        f"当前环境温度约 {value:.1f}°C，低于理想区间。"
                        f"建议加装加热保温装置，将温度提升至 {ideal_lo:.0f}-{ideal_hi:.0f}°C 范围"
                    )
                elif value > ideal_hi:
                    action = (
                        f"当前环境温度约 {value:.1f}°C，高于理想区间。"
                        f"建议采取降温措施（水冷/空调），维持在 {ideal_lo:.0f}-{ideal_hi:.0f}°C"
                    )
                else:
                    action = f"温度处于理想区间，建议维持现状并定期监测"
                rationale = (
                    f"反演估计温度为 {value:.2f}°C（95% CI: [{ci[0]:.2f}, {ci[2]:.2f}]°C）。"
                    f"温度偏差会通过改变水的黏度（±{(abs(value-20)*2):.1f}%）间接影响出流速度。"
                    f"严重度：{severity*100:.0f}%"
                )
            elif name == "viscosity":
                if value > ideal_hi:
                    action = (
                        f"液体黏度偏高（{value:.3f} mPa·s）。"
                        f"建议更换纯净水，必要时过滤去除悬浮杂质，避免微生物滋生"
                    )
                elif value < ideal_lo:
                    action = (
                        f"液体黏度偏低（{value:.3f} mPa·s）。"
                        f"可能水温过高或液体不纯，建议检查水质并更换实验用水"
                    )
                else:
                    action = "黏度处于理想范围，建议保持水体清洁，定期更换"
                rationale = (
                    f"反演估计黏度系数为 {value:.3f}（95% CI: [{ci[0]:.3f}, {ci[2]:.3f}]）。"
                    f"黏度直接决定出流速度（线性反比关系），是计时精度的核心物理参数。"
                    f"严重度：{severity*100:.0f}%"
                )
            elif name == "inflow_amplitude":
                if value > ideal_hi:
                    action = (
                        f"注水波动幅度较大（±{value*100:.1f}%）。"
                        f"建议增设恒压水箱/溢流稳压装置，或增加上壶容量以减小水位波动"
                    )
                else:
                    action = "注水稳定性良好，建议维持现有供水方式"
                rationale = (
                    f"反演估计注水波动幅度为 {value*100:.2f}%。"
                    f"上壶水位波动会逐级传导，最终影响计时级的出流稳定性。"
                    f"严重度：{severity*100:.0f}%"
                )
            elif name == "orifice_wear":
                if value > 0.01:
                    wear_pct = value * 100
                    if wear_pct > 20:
                        action = (
                            f"出水孔径估计已扩大约 {wear_pct:.1f}%，磨损严重。"
                            f"强烈建议更换出水嘴，优先选用红宝石/玛瑙等耐磨材质"
                        )
                    elif wear_pct > 5:
                        action = (
                            f"出水孔径估计已扩大约 {wear_pct:.1f}%，有明显磨损。"
                            f"建议计划更换出水嘴，或重新校准刻度以补偿磨损偏差"
                        )
                    else:
                        action = (
                            f"出水孔径有轻微磨损（约 {wear_pct:.1f}%）。"
                            f"建议纳入定期检查计划，必要时进行预防性更换"
                        )
                else:
                    action = "出水孔径状态良好，建议定期检查并记录磨损情况"
                rationale = (
                    f"反演估计孔径磨损率为 {value*100:.2f}%。"
                    f"孔径增大导致出流加快（出流量与孔径平方成正比）。"
                    f"严重度：{severity*100:.0f}%"
                )
            elif name == "tilt_angle":
                if value > 0.5:
                    action = (
                        f"容器倾斜约 {value:.2f}°，偏差明显。"
                        f"建议安装调平底座和水平仪，重新校准容器水平度"
                    )
                elif value > 0.2:
                    action = (
                        f"容器轻微倾斜（约 {value:.2f}°）。"
                        f"建议检查底座支撑，必要时微调校平"
                    )
                else:
                    action = "容器水平度良好，建议定期使用水平仪检查"
                rationale = (
                    f"反演估计容器倾斜角为 {value:.2f}°（95% CI: [{ci[0]:.2f}°, {ci[2]:.2f}°]）。"
                    f"倾斜会使有效液位高度按余弦因子衰减，静水压力系统性偏低。"
                    f"严重度：{severity*100:.0f}%"
                )
            else:
                action = "进一步分析该参数"
                rationale = f"参数估计值：{value}"

            improvement = min(80.0, max(5.0, severity * 60 + deviation * 10))

            advice_list.append(InversionCalibrationAdvice(
                parameter=name,
                parameter_label=label,
                category=category,
                priority=priority,
                current_estimated=round(value, 4),
                recommended_range=f"{ideal_lo}{unit} ~ {ideal_hi}{unit}",
                action=action,
                rationale=rationale,
                expected_improvement_percent=round(improvement, 2),
            ))

        return advice_list

    @staticmethod
    def _generate_summary(
        optimal_params: Dict[str, float],
        best_fit_err: float,
        avg_fit_err: float,
        rmse: float,
        r2: float,
        advice: List,
    ) -> str:
        if r2 >= 0.95:
            fit_grade = "优秀"
        elif r2 >= 0.85:
            fit_grade = "良好"
        elif r2 >= 0.7:
            fit_grade = "一般"
        else:
            fit_grade = "较差"

        high_priority = [a for a in advice if getattr(a, 'priority', '') == 'high']
        medium_priority = [a for a in advice if getattr(a, 'priority', '') == 'medium']

        temp = optimal_params.get("temperature", 20.0)
        visc = optimal_params.get("viscosity", 1.0)
        inflow = optimal_params.get("inflow_amplitude", 0.0) * 100
        wear = optimal_params.get("orifice_wear", 0.0) * 100
        tilt = optimal_params.get("tilt_angle", 0.0)

        summary_lines = [
            f"联合反演完成，拟合质量{fit_grade}（R² = {r2:.4f}，RMSE = {rmse:.4f} ml）。",
            f"最大点误差 {best_fit_err:.2f}%，平均误差 {avg_fit_err:.2f}%。",
            f"",
            f"反演估计的真实环境参数：",
            f"  · 环境温度：{temp:.2f}°C",
            f"  · 液体黏度：x{visc:.3f}",
            f"  · 注水波动幅度：±{inflow:.2f}%",
            f"  · 孔径磨损：{wear:.2f}%",
            f"  · 容器倾斜：{tilt:.2f}°",
        ]

        if high_priority:
            params = "、".join(getattr(a, 'parameter_label', '') for a in high_priority)
            summary_lines.append(f"")
            summary_lines.append(f"【高优先级校准】{params}存在显著偏差，建议尽快处理：")
            for a in high_priority:
                summary_lines.append(f"  · {getattr(a, 'action', '')}")

        if medium_priority and not high_priority:
            params = "、".join(getattr(a, 'parameter_label', '') for a in medium_priority)
            summary_lines.append(f"")
            summary_lines.append(f"【中优先级校准】{params}有一定偏差，建议择机处理。")

        if not high_priority and not medium_priority:
            summary_lines.append(f"")
            summary_lines.append(f"所有参数估计值处于合理区间，系统状态良好，建议保持常规维护。")

        return "\n".join(summary_lines)

    @staticmethod
    def get_result(db: Session, result_id: int) -> Optional[JointInversionOut]:
        result = db.query(models.JointInversionResult).filter(
            models.JointInversionResult.id == result_id
        ).first()
        if not result:
            return None
        return JointInversionService._to_out_model(result)

    @staticmethod
    def delete_result(db: Session, result_id: int) -> bool:
        result = db.query(models.JointInversionResult).filter(
            models.JointInversionResult.id == result_id
        ).first()
        if not result:
            return False
        db.delete(result)
        db.commit()
        return True

    @staticmethod
    def _to_out_model(r: models.JointInversionResult) -> JointInversionOut:
        ci_list = None
        if r.confidence_intervals:
            ci_list = [
                ConfidenceInterval(**c) if isinstance(c, dict) else c
                for c in r.confidence_intervals
            ]

        top_cands = None
        if r.top_candidates:
            top_cands = [
                InversionCandidate(**c) if isinstance(c, dict) else c
                for c in r.top_candidates
            ]

        conv_hist = None
        if r.convergence_history:
            conv_hist = [
                ConvergencePoint(**c) if isinstance(c, dict) else c
                for c in r.convergence_history
            ]

        aligned_pts = None
        if r.aligned_experiment_points:
            aligned_pts = [
                AlignedDataPoint(**a) if isinstance(a, dict) else a
                for a in r.aligned_experiment_points
            ]

        cal_advice = None
        if r.calibration_advice:
            cal_advice = [
                InversionCalibrationAdvice(**a) if isinstance(a, dict) else a
                for a in r.calibration_advice
            ]

        return JointInversionOut(
            id=r.id,
            project_id=r.project_id,
            experiment_id=r.experiment_id,
            is_multi_vessel=r.is_multi_vessel,
            status=r.status,
            created_at=r.created_at,
            completed_at=r.completed_at,
            algorithm=r.algorithm,
            iteration_count=r.iteration_count,
            particle_count=r.particle_count,
            grid_density=r.grid_density,
            optimal_temperature=r.optimal_temperature,
            optimal_viscosity=r.optimal_viscosity,
            optimal_inflow_amplitude=r.optimal_inflow_amplitude,
            optimal_orifice_wear=r.optimal_orifice_wear,
            optimal_tilt_angle=r.optimal_tilt_angle,
            optimal_params=r.optimal_params,
            best_fit_error=r.best_fit_error,
            avg_fit_error=r.avg_fit_error,
            error_std=r.error_std,
            rmse=r.rmse,
            r_squared=r.r_squared,
            confidence_intervals=ci_list,
            top_candidates=top_cands,
            convergence_history=conv_hist,
            aligned_experiment_points=aligned_pts,
            simulated_optimal_points=r.simulated_optimal_points,
            calibration_advice=cal_advice,
            summary=r.summary,
        )
