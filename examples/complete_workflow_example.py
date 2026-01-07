#!/usr/bin/env python3
"""
完整的端到端需求开发流程示例

本示例演示了从粗粒度、非结构化的初始自然语言需求描述开始,
通过多智能体协作,逐步生成高质量的用户需求列表、需求模型
以及符合 ISO/IEC/IEEE 29148 标准的软件需求规格说明书(SRS)的完整过程。
"""

import sys
import os
import asyncio
import logging
from datetime import datetime
from pathlib import Path

# 添加src到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.config.config_manager import ConfigManager, get_config_manager
from src.orchestrator.orchestrator import RequirementOrchestrator, ProjectConfig, ProcessPhase, ProcessStatus
from src.orchestrator.human_in_loop import HumanReviewManager, FeedbackType
from src.artifact.pool import ArtifactPool
from src.artifact.events import EventBus, EventType
from src.artifact.models import ArtifactType, ArtifactStatus
from src.agent.communication import CommunicationProtocol
from src.knowledge.knowledge_manager import KnowledgeManager
from src.agent.interviewer import InterviewerAgent
from src.agent.enduser import EndUserAgent
from src.agent.deployer import DeployerAgent
from src.agent.analyst import AnalystAgent
from src.agent.archivist import ArchivistAgent
from src.agent.reviewer import ReviewerAgent
from src.agent.customer import Customer

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CompleteWorkflowExample:
    """完整的端到端需求开发流程示例"""
    
    def __init__(self):
        """初始化系统组件"""
        # 初始化配置管理器
        self.config_manager = get_config_manager()
        self.config = self.config_manager.load_config()
        
        # 初始化核心组件
        self.event_bus = EventBus()
        self.artifact_pool = ArtifactPool(
            event_bus=self.event_bus,
            session_id=None
        )
        self.communication_protocol = CommunicationProtocol()
        
        # 初始化知识管理器
        knowledge_config = {
            "base_path": "knowledge",
            "cache_enabled": True,
            "auto_reload": True
        }
        self.knowledge_manager = KnowledgeManager(knowledge_config)
        
        # 初始化编排器
        self.orchestrator = RequirementOrchestrator(
            config_manager=self.config_manager,
            artifact_pool=self.artifact_pool,
            event_bus=self.event_bus,
            communication_protocol=self.communication_protocol
        )
        
        # 初始化人在环路管理器
        self.review_manager = HumanReviewManager(
            artifact_pool=self.artifact_pool,
            event_bus=self.event_bus
        )
        
        # 初始化智能体
        self.agents = {}
        self._initialize_agents()
        
        # 设置事件处理器
        self._setup_event_handlers()
        
        logger.info("系统初始化完成")
    
    def _initialize_agents(self):
        """初始化所有智能体"""
        # 访谈型智能体
        self.agents['interviewer'] = InterviewerAgent(
            knowledge_manager=self.knowledge_manager,
            event_bus=self.event_bus
        )
        
        # 终端用户智能体
        self.agents['enduser'] = EndUserAgent(
            knowledge_manager=self.knowledge_manager,
            event_bus=self.event_bus
        )
        
        # 部署者智能体
        self.agents['deployer'] = DeployerAgent(
            knowledge_manager=self.knowledge_manager,
            event_bus=self.event_bus
        )
        
        # 分析型智能体
        self.agents['analyst'] = AnalystAgent(
            knowledge_manager=self.knowledge_manager,
            event_bus=self.event_bus
        )
        
        # 文档型智能体
        self.agents['archivist'] = ArchivistAgent(
            knowledge_manager=self.knowledge_manager,
            event_bus=self.event_bus
        )
        
        # 审查型智能体
        self.agents['reviewer'] = ReviewerAgent(
            knowledge_manager=self.knowledge_manager,
            event_bus=self.event_bus
        )
        
        logger.info(f"初始化了 {len(self.agents)} 个智能体")
    
    def _setup_event_handlers(self):
        """设置事件处理器"""
        # 监听制品创建事件
        self.event_bus.subscribe_callable(
            [EventType.ARTIFACT_CREATED, EventType.ARTIFACT_UPDATED],
            self._handle_artifact_event
        )
        
        # 监听人在环路事件
        self.event_bus.subscribe_callable(
            [EventType.REVIEW_REQUESTED, EventType.HUMAN_FEEDBACK_RECEIVED],
            self._handle_review_event
        )
    
    def _handle_artifact_event(self, event):
        """处理制品事件"""
        artifact_id = event.payload.get('artifact_id')
        artifact_type = event.payload.get('artifact_type')
        logger.info(f"制品事件: {artifact_type} - {artifact_id}")
    
    def _handle_review_event(self, event):
        """处理审查事件"""
        if event.type == EventType.REVIEW_REQUESTED:
            logger.info(f"审查请求: {event.payload.get('artifact_id')}")
        elif event.type == EventType.HUMAN_FEEDBACK_RECEIVED:
            logger.info(f"收到人工反馈: {event.payload.get('feedback_id')}")
    
    async def run_complete_workflow(self, initial_requirement: str):
        """
        运行完整的需求开发流程
        
        Args:
            initial_requirement: 初始的粗粒度、非结构化需求描述
        """
        logger.info("=" * 80)
        logger.info("开始完整的需求开发流程")
        logger.info("=" * 80)
        logger.info(f"初始需求描述:\n{initial_requirement}\n")
        
        # 1. 创建项目配置
        project_config = ProjectConfig(
            project_name="示例项目",
            domain="web_application",
            stakeholders=["业务方", "终端用户", "系统管理员"],
            target_environment="cloud",
            compliance_requirements=["ISO/IEC/IEEE 29148"],
            quality_standards=["IEEE 830"],
            review_points=["url_generation", "model_creation", "srs_generation"],
            timeout_minutes=1440,
            max_iterations=3
        )
        
        # 2. 启动需求开发流程
        session = self.orchestrator.start_requirement_process(
            project_config=project_config,
            created_by="workflow_example"
        )
        
        logger.info(f"创建了流程会话: {session.session_id}")
        
        # 3. 阶段1: 需求访谈
        await self._phase_interview(session, initial_requirement)
        
        # 4. 阶段2: 用户建模
        await self._phase_user_modeling(session)
        
        # 5. 阶段3: 部署分析
        await self._phase_deployment_analysis(session)
        
        # 6. 阶段4: 需求分析
        await self._phase_requirement_analysis(session)
        
        # 7. 阶段5: 用户需求列表审查(人在环路)
        await self._phase_url_review(session)
        
        # 8. 阶段6: 需求建模
        await self._phase_requirement_modeling(session)
        
        # 9. 阶段7: 需求模型审查(人在环路)
        await self._phase_model_review(session)
        
        # 10. 阶段8: SRS生成
        await self._phase_srs_generation(session)
        
        # 11. 阶段9: SRS审查(人在环路)
        await self._phase_srs_review(session)
        
        # 12. 阶段10: 质量保证
        await self._phase_quality_assurance(session)
        
        # 13. 完成流程
        logger.info("=" * 80)
        logger.info("需求开发流程完成")
        logger.info("=" * 80)
        
        # 输出最终结果摘要
        self._print_final_summary(session)
    
    async def _phase_interview(self, session, initial_requirement: str):
        """阶段1: 需求访谈"""
        logger.info("\n" + "=" * 80)
        logger.info("阶段1: 需求访谈")
        logger.info("=" * 80)
        
        # 设置智能体会话
        self.agents['interviewer'].start_session(session.session_id)
        
        # 创建模拟客户
        customer = Customer(
            name="业务方代表",
            role="product_manager",
            domain="web_application"
        )
        
        # 进行访谈
        interview_record = self.agents['interviewer'].chat_with_customer(
            customer=customer,
            stakeholder_type="customer"
        )
        
        # 将访谈记录存入制品池
        interview_artifact = self.agents['interviewer'].create_interview_artifact(interview_record)
        artifact_id = self.artifact_pool.store_artifact(interview_artifact, created_by="interviewer")
        
        logger.info(f"访谈完成,生成访谈记录制品: {artifact_id}")
        logger.info(f"访谈轮次: {interview_record.get('total_turns', 0)}")
        logger.info(f"识别需求数: {len(interview_record.get('requirements_identified', []))}")
    
    async def _phase_user_modeling(self, session):
        """阶段2: 用户建模"""
        logger.info("\n" + "=" * 80)
        logger.info("阶段2: 用户建模")
        logger.info("=" * 80)
        
        # 设置智能体会话
        self.agents['enduser'].start_session(session.session_id)
        
        # 获取访谈记录
        from src.artifact.models import ArtifactQuery
        query = ArtifactQuery(artifact_type=ArtifactType.INTERVIEW_RECORD)
        interview_artifacts = self.artifact_pool.query_artifacts(query)
        
        if not interview_artifacts:
            logger.warning("未找到访谈记录,使用默认上下文")
            domain = "web_application"
            context = {}
        else:
            latest_interview = max(interview_artifacts, key=lambda a: a.updated_at)
            domain = latest_interview.content.get('domain', 'web_application')
            context = latest_interview.content
        
        # 创建用户角色
        personas = self.agents['enduser'].create_user_personas(
            domain=domain,
            context=context
        )
        
        logger.info(f"创建了 {len(personas)} 个用户角色")
        
        # 生成用户场景
        system_context = {
            "domain": domain,
            "type": "web_application"
        }
        scenarios = self.agents['enduser'].generate_user_scenarios(
            personas=personas,
            system_context=system_context
        )
        
        logger.info(f"生成了 {len(scenarios)} 个用户场景")
        
        # 识别痛点
        pain_points = self.agents['enduser'].identify_pain_points(
            scenarios=scenarios
        )
        
        logger.info(f"识别了 {len(pain_points)} 个用户痛点")
    
    async def _phase_deployment_analysis(self, session):
        """阶段3: 部署分析"""
        logger.info("\n" + "=" * 80)
        logger.info("阶段3: 部署分析")
        logger.info("=" * 80)
        
        # 设置智能体会话
        self.agents['deployer'].start_session(session.session_id)
        
        # 分析部署约束
        target_environment = session.project_config.target_environment
        system_context = {
            "domain": session.project_config.domain,
            "scale": "medium",
            "architecture": "microservices"
        }
        
        constraints = self.agents['deployer'].analyze_deployment_constraints(
            target_environment=target_environment,
            system_context=system_context
        )
        
        logger.info(f"识别了 {len(constraints)} 个部署约束")
        
        # 识别安全需求
        security_reqs = self.agents['deployer'].identify_security_requirements(
            system_type="web_application",
            threat_model={
                "assets": ["user_data", "authentication"],
                "threats": ["unauthorized_access", "data_breach"]
            }
        )
        
        logger.info(f"识别了 {len(security_reqs)} 个安全需求")
        
        # 评估合规需求
        compliance_reqs = self.agents['deployer'].assess_compliance_requirements(
            domain=session.project_config.domain,
            region="global",
            data_types=["PII"]
        )
        
        logger.info(f"识别了 {len(compliance_reqs)} 个合规需求")
    
    async def _phase_requirement_analysis(self, session):
        """阶段4: 需求分析"""
        logger.info("\n" + "=" * 80)
        logger.info("阶段4: 需求分析")
        logger.info("=" * 80)
        
        # 设置智能体会话
        self.agents['analyst'].start_session(session.session_id)
        
        # 获取用户需求
        from src.artifact.models import ArtifactQuery
        user_requirements = []
        query = ArtifactQuery(artifact_type=ArtifactType.INTERVIEW_RECORD)
        interview_artifacts = self.artifact_pool.query_artifacts(query)
        
        for artifact in interview_artifacts:
            requirements = artifact.content.get('requirements_discovered', {})
            user_requirements.extend(requirements.get('functional_requirements', []))
            user_requirements.extend(requirements.get('non_functional_requirements', []))
        
        if not user_requirements:
            logger.warning("未找到用户需求,使用默认需求")
            user_requirements = [
                {
                    "id": "user-req-1",
                    "title": "用户登录",
                    "description": "用户需要能够安全地登录系统",
                    "priority": "high",
                    "type": "functional"
                }
            ]
        
        # 转换为系统需求
        context = {
            "domain": session.project_config.domain,
            "environment": session.project_config.target_environment
        }
        
        system_requirements = self.agents['analyst'].transform_to_system_requirements(
            user_requirements=user_requirements,
            context=context
        )
        
        logger.info(f"转换了 {len(system_requirements)} 个系统需求")
        
        # 创建需求模型
        stakeholder_info = {
            "end_users": {
                "role": "主要系统用户",
                "responsibilities": ["使用系统功能", "提供反馈"]
            }
        }
        
        requirement_model = self.agents['analyst'].create_requirement_model(
            requirements=system_requirements,
            stakeholder_info=stakeholder_info
        )
        
        logger.info(f"创建了需求模型: {requirement_model.id}")
        
        # 建立可追溯性矩阵
        traceability_matrix = self.agents['analyst'].establish_traceability_matrix(
            requirements=system_requirements,
            user_requirements=user_requirements
        )
        
        logger.info(f"建立了可追溯性矩阵,包含 {len(traceability_matrix.links)} 个链接")
    
    async def _phase_url_review(self, session):
        """阶段5: 用户需求列表审查(人在环路)"""
        logger.info("\n" + "=" * 80)
        logger.info("阶段5: 用户需求列表审查(人在环路)")
        logger.info("=" * 80)
        
        # 查找用户需求列表制品
        from src.artifact.models import ArtifactQuery
        query = ArtifactQuery(artifact_type=ArtifactType.USER_REQUIREMENTS_LIST)
        url_artifacts = self.artifact_pool.query_artifacts(query)
        
        if not url_artifacts:
            logger.warning("未找到用户需求列表制品")
            return
        
        latest_url = max(url_artifacts, key=lambda a: a.updated_at)
        
        # 创建审查点
        review_point = self.review_manager.create_review_point(
            session_id=session.session_id,
            artifact_id=latest_url.id,
            phase="URL_REVIEW",
            description="审查用户需求列表的完整性和准确性",
            timeout_minutes=1440,
            priority=3
        )
        
        logger.info(f"创建了审查点: {review_point.id}")
        logger.info("等待人工审查...")
        
        # 模拟人工审查(在实际应用中,这里会暂停等待真实的人工输入)
        # 为了演示,我们自动批准
        feedback = self.review_manager.submit_feedback(
            review_point_id=review_point.id,
            reviewer="示例审查者",
            feedback_type=FeedbackType.APPROVAL,
            content="用户需求列表审查通过",
            approval_status=True
        )
        
        logger.info(f"收到审查反馈: {feedback.id}")
        
        # 恢复流程
        self.orchestrator.resume_after_review(
            session_id=session.session_id,
            feedback=feedback.to_dict()
        )
    
    async def _phase_requirement_modeling(self, session):
        """阶段6: 需求建模"""
        logger.info("\n" + "=" * 80)
        logger.info("阶段6: 需求建模")
        logger.info("=" * 80)
        
        # 需求模型已在阶段4创建,这里主要是确认和优化
        model_artifacts = self.artifact_pool.query_artifacts(
            type=ArtifactType.REQUIREMENT_MODEL
        )
        
        if model_artifacts:
            latest_model = max(model_artifacts, key=lambda a: a.updated_at)
            logger.info(f"使用现有需求模型: {latest_model.id}")
        else:
            logger.warning("未找到需求模型")
    
    async def _phase_model_review(self, session):
        """阶段7: 需求模型审查(人在环路)"""
        logger.info("\n" + "=" * 80)
        logger.info("阶段7: 需求模型审查(人在环路)")
        logger.info("=" * 80)
        
        # 查找需求模型制品
        from src.artifact.models import ArtifactQuery
        query = ArtifactQuery(artifact_type=ArtifactType.REQUIREMENT_MODEL)
        model_artifacts = self.artifact_pool.query_artifacts(query)
        
        if not model_artifacts:
            logger.warning("未找到需求模型制品")
            return
        
        latest_model = max(model_artifacts, key=lambda a: a.updated_at)
        
        # 创建审查点
        review_point = self.review_manager.create_review_point(
            session_id=session.session_id,
            artifact_id=latest_model.id,
            phase="MODEL_REVIEW",
            description="审查需求模型的结构和完整性",
            timeout_minutes=1440,
            priority=3
        )
        
        logger.info(f"创建了审查点: {review_point.id}")
        
        # 模拟人工审查
        feedback = self.review_manager.submit_feedback(
            review_point_id=review_point.id,
            reviewer="示例审查者",
            feedback_type=FeedbackType.APPROVAL,
            content="需求模型审查通过",
            approval_status=True
        )
        
        logger.info(f"收到审查反馈: {feedback.id}")
        
        # 恢复流程
        self.orchestrator.resume_after_review(
            session_id=session.session_id,
            feedback=feedback.to_dict()
        )
    
    async def _phase_srs_generation(self, session):
        """阶段8: SRS生成"""
        logger.info("\n" + "=" * 80)
        logger.info("阶段8: SRS生成")
        logger.info("=" * 80)
        
        # 设置智能体会话
        self.agents['archivist'].start_session(session.session_id)
        
        # 获取系统需求和需求模型
        system_requirements = []
        requirement_model = {}
        
        # 从制品池获取需求
        from src.artifact.models import ArtifactQuery
        query = ArtifactQuery(artifact_type=ArtifactType.USER_REQUIREMENTS_LIST)
        req_artifacts = self.artifact_pool.query_artifacts(query)
        
        for artifact in req_artifacts:
            reqs = artifact.content.get('requirements', [])
            system_requirements.extend(reqs)
        
        # 获取需求模型
        query = ArtifactQuery(artifact_type=ArtifactType.REQUIREMENT_MODEL)
        model_artifacts = self.artifact_pool.query_artifacts(query)
        
        if model_artifacts:
            latest_model = max(model_artifacts, key=lambda a: a.updated_at)
            requirement_model = latest_model.content
        
        # 项目信息
        project_info = {
            "name": session.project_config.project_name,
            "version": "1.0",
            "authors": ["ArchivistAgent"],
            "template": "iso_29148"
        }
        
        # 生成SRS文档
        srs_document = self.agents['archivist'].generate_srs_document(
            requirements=system_requirements,
            requirement_model=requirement_model,
            project_info=project_info
        )
        
        logger.info(f"生成了SRS文档: {srs_document.id}")
        logger.info(f"文档标题: {srs_document.title}")
        logger.info(f"标准合规: {srs_document.standard_compliance}")
        logger.info(f"章节数: {len(srs_document.sections)}")
        
        # 确保标准合规
        compliance_report = self.agents['archivist'].ensure_standard_compliance(
            document=srs_document,
            standard="ISO/IEC/IEEE 29148"
        )
        
        logger.info(f"合规性检查完成,得分: {compliance_report.compliance_score:.2f}")
    
    async def _phase_srs_review(self, session):
        """阶段9: SRS审查(人在环路)"""
        logger.info("\n" + "=" * 80)
        logger.info("阶段9: SRS审查(人在环路)")
        logger.info("=" * 80)
        
        # 查找SRS文档制品
        from src.artifact.models import ArtifactQuery
        query = ArtifactQuery(artifact_type=ArtifactType.SRS_DOCUMENT)
        srs_artifacts = self.artifact_pool.query_artifacts(query)
        
        if not srs_artifacts:
            logger.warning("未找到SRS文档制品")
            return
        
        latest_srs = max(srs_artifacts, key=lambda a: a.updated_at)
        
        # 创建审查点
        review_point = self.review_manager.create_review_point(
            session_id=session.session_id,
            artifact_id=latest_srs.id,
            phase="SRS_REVIEW",
            description="审查软件需求规格说明书的完整性和质量",
            timeout_minutes=1440,
            priority=5
        )
        
        logger.info(f"创建了审查点: {review_point.id}")
        
        # 模拟人工审查
        feedback = self.review_manager.submit_feedback(
            review_point_id=review_point.id,
            reviewer="示例审查者",
            feedback_type=FeedbackType.APPROVAL,
            content="SRS文档审查通过,符合ISO/IEC/IEEE 29148标准",
            approval_status=True
        )
        
        logger.info(f"收到审查反馈: {feedback.id}")
        
        # 恢复流程
        self.orchestrator.resume_after_review(
            session_id=session.session_id,
            feedback=feedback.to_dict()
        )
    
    async def _phase_quality_assurance(self, session):
        """阶段10: 质量保证"""
        logger.info("\n" + "=" * 80)
        logger.info("阶段10: 质量保证")
        logger.info("=" * 80)
        
        # 设置智能体会话
        self.agents['reviewer'].start_session(session.session_id)
        
        # 获取SRS文档
        from src.artifact.models import ArtifactQuery
        query = ArtifactQuery(artifact_type=ArtifactType.SRS_DOCUMENT)
        srs_artifacts = self.artifact_pool.query_artifacts(query)
        
        if not srs_artifacts:
            logger.warning("未找到SRS文档")
            return
        
        latest_srs = max(srs_artifacts, key=lambda a: a.updated_at)
        srs_content = latest_srs.content
        
        # 验证一致性
        consistency_report = self.agents['reviewer'].validate_consistency(
            srs_document=srs_content
        )
        
        logger.info(f"一致性验证完成,得分: {consistency_report.consistency_score:.2f}")
        logger.info(f"发现 {len(consistency_report.violations)} 个一致性违规")
        
        # 检查完整性
        system_requirements = []
        query = ArtifactQuery(artifact_type=ArtifactType.USER_REQUIREMENTS_LIST)
        req_artifacts = self.artifact_pool.query_artifacts(query)
        
        for artifact in req_artifacts:
            reqs = artifact.content.get('requirements', [])
            system_requirements.extend(reqs)
        
        completeness_report = self.agents['reviewer'].check_completeness(
            srs_document=srs_content,
            requirements=system_requirements
        )
        
        logger.info(f"完整性检查完成,得分: {completeness_report.completeness_score:.2f}")
        logger.info(f"发现 {len(completeness_report.gaps)} 个完整性缺口")
        
        # 验证可追溯性
        traceability_matrix = {}
        query = ArtifactQuery(artifact_type=ArtifactType.REQUIREMENT_MODEL)
        model_artifacts = self.artifact_pool.query_artifacts(query)
        
        if model_artifacts:
            latest_model = max(model_artifacts, key=lambda a: a.updated_at)
            traceability_matrix = latest_model.content.get('traceability', {})
        
        traceability_report = self.agents['reviewer'].verify_traceability(
            srs_document=srs_content,
            traceability_matrix=traceability_matrix
        )
        
        logger.info(f"可追溯性验证完成,得分: {traceability_report.traceability_score:.2f}")
        logger.info(f"发现 {len(traceability_report.issues)} 个可追溯性问题")
        
        # 综合质量评估
        quality_metrics = self.agents['reviewer'].assess_quality_metrics(
            srs_document=srs_content
        )
        
        logger.info(f"综合质量评估完成")
        logger.info(f"总体得分: {quality_metrics.overall_score:.2f}")
        logger.info(f"一致性: {quality_metrics.consistency_score:.2f}")
        logger.info(f"完整性: {quality_metrics.completeness_score:.2f}")
        logger.info(f"可追溯性: {quality_metrics.traceability_score:.2f}")
        logger.info(f"清晰度: {quality_metrics.clarity_score:.2f}")
        logger.info(f"可验证性: {quality_metrics.verifiability_score:.2f}")
    
    def _print_final_summary(self, session):
        """打印最终结果摘要"""
        logger.info("\n" + "=" * 80)
        logger.info("最终结果摘要")
        logger.info("=" * 80)
        
        # 获取所有制品
        from src.artifact.models import ArtifactQuery
        query = ArtifactQuery()
        all_artifacts = self.artifact_pool.query_artifacts(query)
        
        # 按类型统计
        artifact_counts = {}
        for artifact in all_artifacts:
            artifact_type = artifact.type.value
            artifact_counts[artifact_type] = artifact_counts.get(artifact_type, 0) + 1
        
        logger.info(f"\n生成的制品统计:")
        for artifact_type, count in artifact_counts.items():
            logger.info(f"  - {artifact_type}: {count}")
        
        # 获取SRS文档
        srs_artifacts = [a for a in all_artifacts if a.type == ArtifactType.SRS_DOCUMENT]
        if srs_artifacts:
            latest_srs = max(srs_artifacts, key=lambda a: a.updated_at)
            logger.info(f"\n最终SRS文档:")
            logger.info(f"  - ID: {latest_srs.id}")
            logger.info(f"  - 状态: {latest_srs.status.value}")
            logger.info(f"  - 创建时间: {latest_srs.created_at}")
            logger.info(f"  - 更新时间: {latest_srs.updated_at}")
            
            srs_content = latest_srs.content
            if isinstance(srs_content, dict):
                logger.info(f"  - 标题: {srs_content.get('title', 'N/A')}")
                logger.info(f"  - 版本: {srs_content.get('version', 'N/A')}")
                logger.info(f"  - 标准合规: {', '.join(srs_content.get('standard_compliance', []))}")
                logger.info(f"  - 章节数: {len(srs_content.get('sections', []))}")
        
        # 获取审查历史
        review_history = self.review_manager.get_review_history(session.session_id)
        logger.info(f"\n审查历史:")
        logger.info(f"  - 审查次数: {len(review_history)}")
        for review in review_history:
            review_point = review.get('review_point', {})
            feedback_list = review.get('feedback', [])
            if feedback_list:
                feedback = feedback_list[0]
                logger.info(f"  - {review_point.get('phase', 'N/A')}: {feedback.get('feedback_type', 'N/A')}")
        
        logger.info("\n" + "=" * 80)
        logger.info("流程完成!")
        logger.info("=" * 80)


async def main():
    """主函数"""
    # 初始需求描述(粗粒度、非结构化)
    initial_requirement = """
    我们需要开发一个在线学习管理系统。系统应该允许学生注册课程、查看课程内容、
    提交作业、参加考试,并查看成绩。教师应该能够创建课程、上传教学材料、布置作业、
    批改作业和考试,以及管理学生。系统管理员需要能够管理用户账户、课程和系统设置。
    系统需要支持多种设备访问,包括桌面和移动设备。系统应该安全可靠,能够处理大量
    并发用户。我们希望系统能够快速响应,界面友好易用。
    """
    
    # 创建示例实例
    example = CompleteWorkflowExample()
    
    # 运行完整流程
    await example.run_complete_workflow(initial_requirement)


if __name__ == "__main__":
    asyncio.run(main())

