from sqlalchemy.orm import Session
from database import models
from schemas import (
    ClepsydraConfigUpdate, ExperimentRecordCreate,
    ScaleSchemeUpdate,
)


class ValidationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


ERROR_THRESHOLD = 5.0


class ValidationService:

    @staticmethod
    def validate_record(
        db: Session,
        experiment_id: int,
        data: ExperimentRecordCreate,
        capacity: float,
    ) -> None:
        if data.water_level > capacity:
            raise ValidationError(
                f"记录水位 {data.water_level} ml 超过漏壶容量 {capacity} ml"
            )

        records = (
            db.query(models.ExperimentRecord)
            .filter(models.ExperimentRecord.experiment_id == experiment_id)
            .order_by(models.ExperimentRecord.time_point)
            .all()
        )

        for rec in records:
            if abs(rec.time_point - data.time_point) < 1e-6:
                raise ValidationError(
                    f"时间节点 {data.time_point} 分钟已存在，不能重复录入"
                )

        if records:
            last_time = records[-1].time_point
            if data.time_point <= last_time:
                raise ValidationError(
                    f"时间节点必须递增，新值 {data.time_point} 必须大于上一节点 {last_time}"
                )

    @staticmethod
    def validate_scale_scheme(
        scheme: ScaleSchemeUpdate,
        capacity: float,
    ) -> None:
        for mark in scheme.marks:
            if mark.target_water_level > capacity:
                raise ValidationError(
                    f"刻度 #{mark.mark_index} 的目标水位 {mark.target_water_level} ml 超过容量 {capacity} ml"
                )
