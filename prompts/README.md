# 提示词文件说明

本文件夹包含所有智能体的系统提示词（profile prompts）和操作提示词（action prompts）。

## 文件命名规则

- **Profile提示词**: `{agent_name}_profile.txt` - 定义智能体的角色、使命、工作流程和思考方式
- **Action提示词**: `{agent_name}_action_{action_name}.txt` - 定义具体操作的执行指令

## 智能体列表

### 1. InterviewerAgent (访谈者智能体)
- `interviewer_profile.txt` - 系统提示词
- `interviewer_action_conduct_interview.txt` - 执行访谈操作
- `interviewer_action_create_interview_record.txt` - 创建访谈记录
- `interviewer_action_create_user_requirements_list.txt` - 创建用户需求列表

### 2. EndUserAgent (终端用户智能体)
- `enduser_profile.txt` - 系统提示词
- `enduser_action_create_personas.txt` - 创建用户角色
- `enduser_action_generate_scenarios.txt` - 生成用户场景
- `enduser_action_identify_pain_points.txt` - 识别痛点
- `enduser_action_define_nfrs.txt` - 定义非功能性需求

### 3. DeployerAgent (部署者智能体)
- `deployer_profile.txt` - 系统提示词
- `deployer_action_analyze_deployment_constraints.txt` - 分析部署约束
- `deployer_action_identify_security_requirements.txt` - 识别安全需求
- `deployer_action_assess_compliance.txt` - 评估合规性
- `deployer_action_define_performance_criteria.txt` - 定义性能标准

### 4. AnalystAgent (分析者智能体)
- `analyst_profile.txt` - 系统提示词
- `analyst_action_transform_requirements.txt` - 转换需求
- `analyst_action_create_requirement_model.txt` - 创建需求模型
- `analyst_action_establish_traceability.txt` - 建立可追溯性
- `analyst_action_prioritize_requirements.txt` - 优先级排序
- `analyst_action_detect_conflicts.txt` - 检测冲突

### 5. ArchivistAgent (文档归档智能体)
- `archivist_profile.txt` - 系统提示词
- `archivist_action_generate_srs.txt` - 生成SRS文档
- `archivist_action_apply_template.txt` - 应用模板
- `archivist_action_validate_compliance.txt` - 验证合规性

### 6. ReviewerAgent (审查者智能体)
- `reviewer_profile.txt` - 系统提示词
- `reviewer_action_validate_consistency.txt` - 验证一致性
- `reviewer_action_check_completeness.txt` - 检查完整性
- `reviewer_action_verify_traceability.txt` - 验证可追溯性
- `reviewer_action_assess_quality.txt` - 评估质量
- `reviewer_action_generate_recommendations.txt` - 生成改进建议

## 提示词结构

### Profile提示词包含：
1. **Mission** - 智能体的使命和目标
2. **Personality** - 智能体的个性特征和工作风格
3. **Workflow** - 工作流程和步骤
4. **Experience & Preferred Practices** - 经验和最佳实践
5. **Internal Chain of Thought** - 内部思考链（仅对智能体可见）

### Action提示词包含：
1. **Action** - 操作名称和描述
2. **Context** - 上下文信息（使用占位符如 {variable_name}）
3. **Instructions** - 具体执行指令

## 使用说明

这些提示词文件可以直接被智能体代码读取和使用。在代码中，智能体通过 `_create_profile_prompt()` 和 `_get_action_prompt()` 方法加载这些提示词。

如果需要修改提示词，可以直接编辑对应的txt文件，然后更新智能体代码中的相应方法。

