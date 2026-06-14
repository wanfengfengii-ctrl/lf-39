from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean,
    ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship

from database.connection import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    researcher = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="draft")
    needs_recheck = Column(Boolean, default=False)
    is_multi_vessel = Column(Boolean, default=False)

    config = relationship(
        "ClepsydraConfig", back_populates="project",
        uselist=False, cascade="all, delete-orphan"
    )
    scale_scheme = relationship(
        "ScaleScheme", back_populates="project",
        uselist=False, cascade="all, delete-orphan"
    )
    experiments = relationship(
        "Experiment", back_populates="project",
        cascade="all, delete-orphan", order_by="Experiment.round_number"
    )
    vessels = relationship(
        "Vessel", back_populates="project",
        cascade="all, delete-orphan", order_by="Vessel.level_index"
    )
    flow_relations = relationship(
        "VesselFlowRelation", back_populates="project",
        cascade="all, delete-orphan"
    )


class ClepsydraConfig(Base):
    __tablename__ = "clepsydra_configs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), unique=True, nullable=False)
    capacity = Column(Float, nullable=False)
    water_inlet_type = Column(String(20), default="gravity")
    outlet_diameter = Column(Float, nullable=False)
    target_duration = Column(Float, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    params_changed = Column(Boolean, default=False)

    project = relationship("Project", back_populates="config")


class Vessel(Base):
    __tablename__ = "vessels"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    level_index = Column(Integer, nullable=False)
    name = Column(String(50), nullable=False)
    role = Column(String(20), default="middle")
    capacity = Column(Float, nullable=False)
    water_inlet_type = Column(String(20), default="gravity")
    outlet_diameter = Column(Float, nullable=False)
    target_duration = Column(Float, nullable=True)
    initial_level = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="vessels")
    scale_scheme = relationship(
        "ScaleScheme", back_populates="vessel",
        uselist=False, cascade="all, delete-orphan"
    )
    records = relationship(
        "VesselExperimentRecord", back_populates="vessel",
        cascade="all, delete-orphan"
    )


class VesselFlowRelation(Base):
    __tablename__ = "vessel_flow_relations"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    upstream_vessel_id = Column(Integer, ForeignKey("vessels.id"), nullable=False)
    downstream_vessel_id = Column(Integer, ForeignKey("vessels.id"), nullable=False)
    flow_coefficient = Column(Float, default=1.0)
    delay_seconds = Column(Float, default=0.0)
    relation_type = Column(String(20), default="series")

    project = relationship("Project", back_populates="flow_relations")


class ScaleScheme(Base):
    __tablename__ = "scale_schemes"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    vessel_id = Column(Integer, ForeignKey("vessels.id"), unique=True, nullable=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="scale_scheme")
    vessel = relationship("Vessel", back_populates="scale_scheme")
    marks = relationship(
        "ScaleMark", back_populates="scheme",
        cascade="all, delete-orphan", order_by="ScaleMark.mark_index"
    )


class ScaleMark(Base):
    __tablename__ = "scale_marks"

    id = Column(Integer, primary_key=True, index=True)
    scheme_id = Column(Integer, ForeignKey("scale_schemes.id"), nullable=False)
    mark_index = Column(Integer, nullable=False)
    target_time = Column(Float, nullable=False)
    target_water_level = Column(Float, nullable=False)

    scheme = relationship("ScaleScheme", back_populates="marks")


class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    round_number = Column(Integer, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    finalized_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="recording")
    needs_recheck = Column(Boolean, default=False)
    total_error = Column(Float, nullable=True)
    is_multi_vessel = Column(Boolean, default=False)

    project = relationship("Project", back_populates="experiments")
    records = relationship(
        "ExperimentRecord", back_populates="experiment",
        cascade="all, delete-orphan", order_by="ExperimentRecord.time_point"
    )
    vessel_records = relationship(
        "VesselExperimentRecord", back_populates="experiment",
        cascade="all, delete-orphan"
    )


class ExperimentRecord(Base):
    __tablename__ = "experiment_records"

    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable=False)
    time_point = Column(Float, nullable=False)
    water_level = Column(Float, nullable=False)
    computed_flow_rate = Column(Float, nullable=True)
    time_error = Column(Float, nullable=True)

    experiment = relationship("Experiment", back_populates="records")


class VesselExperimentRecord(Base):
    __tablename__ = "vessel_experiment_records"

    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable=False)
    vessel_id = Column(Integer, ForeignKey("vessels.id"), nullable=False)
    time_point = Column(Float, nullable=False)
    water_level = Column(Float, nullable=False)
    computed_flow_rate = Column(Float, nullable=True)
    time_error = Column(Float, nullable=True)
    inflow_rate = Column(Float, nullable=True)

    experiment = relationship("Experiment", back_populates="vessel_records")
    vessel = relationship("Vessel", back_populates="records")
