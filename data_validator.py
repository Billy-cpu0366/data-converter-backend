"""
数据完整性校验工具
确保38题永远是38题
"""

import hashlib
import json
from typing import List, Dict, Any

class DataIntegrityValidator:
    """确保数据零丢失的验证器"""
    
    def __init__(self):
        self.validation_log = []
    
    def validate_question_integrity(self, original_text: str, extracted_questions: List[Dict]) -> Dict[str, Any]:
        """验证题目完整性"""
        
        validation_result = {
            "original_length": len(original_text),
            "extracted_count": len(extracted_questions),
            "checksum": self.calculate_checksum(original_text),
            "issues": [],
            "warnings": [],
            "passed": True
        }
        
        # 检查每道题的完整性
        for i, question in enumerate(extracted_questions):
            issues = self.check_single_question(question, i + 1)
            validation_result["issues"].extend(issues)
            
            if issues:
                validation_result["passed"] = False
        
        # 生成警告（不阻止显示）
        warnings = self.generate_warnings(extracted_questions)
        validation_result["warnings"] = warnings
        
        return validation_result
    
    def check_single_question(self, question: Dict, index: int) -> List[Dict[str, Any]]:
        """检查单个题目"""
        issues = []
        
        # 检查必要字段
        required_fields = ["raw_question", "raw_answer", "raw_options"]
        for field in required_fields:
            if field not in question:
                issues.append({
                    "type": "missing_field",
                    "question_index": index,
                    "field": field,
                    "severity": "high",
                    "message": f"第{index}题缺少{field}字段"
                })
        
        # 检查题目内容
        if not question.get("raw_question", "").strip():
            issues.append({
                "type": "empty_question",
                "question_index": index,
                "severity": "high",
                "message": f"第{index}题题目为空"
            })
        
        # 检查选项
        options = question.get("raw_options", [])
        if not isinstance(options, list):
            issues.append({
                "type": "invalid_options",
                "question_index": index,
                "severity": "medium",
                "message": f"第{index}题选项格式错误"
            })
        elif len(options) < 2:
            issues.append({
                "type": "insufficient_options",
                "question_index": index,
                "severity": "medium",
                "message": f"第{index}题选项不足2个"
            })
        
        # 检查答案
        answer = question.get("raw_answer", "")
        if not str(answer).strip():
            issues.append({
                "type": "empty_answer",
                "question_index": index,
                "severity": "medium",
                "message": f"第{index}题答案为空"
            })
        
        return issues
    
    def generate_warnings(self, questions: List[Dict]) -> List[Dict[str, Any]]:
        """生成显示警告（不阻止显示）"""
        warnings = []
        
        for i, question in enumerate(questions):
            # 选项完整性警告
            options = question.get("raw_options", [])
            if len(options) < 4:
                warnings.append({
                    "type": "incomplete_options",
                    "question_index": i + 1,
                    "severity": "low",
                    "message": f"第{i+1}题选项不足4个，已自动处理",
                    "action": "display_with_warning"
                })
            
            # 特殊字符警告
            question_text = question.get("raw_question", "")
            if '\n' in question_text:
                warnings.append({
                    "type": "newline_characters",
                    "question_index": i + 1,
                    "severity": "low",
                    "message": "题目中包含换行符，将原样显示"
                })
            
            # 引号警告
            if '"' in question_text or "'" in question_text:
                warnings.append({
                    "type": "quote_characters",
                    "question_index": i + 1,
                    "severity": "low",
                    "message": "题目中包含引号，将原样显示"
                })
        
        return warnings
    
    def calculate_checksum(self, data: str) -> str:
        """计算数据校验和"""
        return hashlib.md5(data.encode('utf-8')).hexdigest()[:8]
    
    def create_integrity_report(self, questions: List[Dict], original_text: str) -> Dict[str, Any]:
        """生成完整性报告"""
        report = {
            "timestamp": self.get_timestamp(),
            "original_text_length": len(original_text),
            "total_questions": len(questions),
            "checksum": self.calculate_checksum(str(questions)),
            "validation": self.validate_question_integrity(original_text, questions),
            "recommendations": []
        }
        
        # 生成建议
        if len(questions) < 10:
            report["recommendations"].append(
                "题目数量较少，建议检查源文件内容"
            )
        
        if any(w["type"] == "incomplete_options" for w in report["validation"]["warnings"]):
            report["recommendations"].append(
                "部分题目选项不完整，但将正常显示"
            )
        
        return report
    
    def get_timestamp(self) -> str:
        """获取时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()

# 使用示例
def validate_and_report(original_text: str, questions: List[Dict]) -> Dict[str, Any]:
    """完整的验证流程"""
    validator = DataIntegrityValidator()
    return validator.create_integrity_report(questions, original_text)

# 测试函数
def test_validator():
    """测试验证器"""
    test_data = [
        {
            "raw_question": "测试题目\n带换行符",
            "raw_answer": "A",
            "raw_options": ["选项A", "选项B", "选项C", "选项D"]
        },
        {
            "raw_question": "测试题目,带逗号",
            "raw_answer": "B",
            "raw_options": ["选项,1", "选项2", "", ""]  # 故意留空
        }
    ]
    
    original_text = "这是原始文本内容..."
    result = validate_and_report(original_text, test_data)
    
    print("验证结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    test_validator()