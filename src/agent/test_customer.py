import sys
import os
import json
from pathlib import Path

# Thêm thư mục root của project vào sys.path để tránh lỗi "relative import"
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from src.agent.customer import Customer
from src.agent.interviewer import Interviewer


def main():
    print("--- Testing Customer Agent with Interviewer ---")
    try:
        # 1. Khởi tạo Customer Agent
        customer = Customer()

        # 2. Cấu hình cho Interviewer sử dụng OpenAI
        # Bạn cần đảm bảo đã set biến môi trường OPENAI_API_KEY trước khi chạy
        # hoặc có cơ chế load API key riêng trong project.
        interviewer_config = {
            "llm": {
                "provider": "openai",
                "model": "gpt-3.5-turbo",  # Bạn có thể đổi sang "gpt-4o" nếu muốn
                "temperature": 0.7
            },
            "max_customer_turns": 5  # Giới hạn số lượt hỏi/đáp để test nhanh
        }

        # Khởi tạo Interviewer
        interviewer = Interviewer(config_path=interviewer_config)

        print("\n[Start] Interviewer đang bắt đầu cuộc trò chuyện với Customer...")
        print("Lưu ý: Bạn sẽ đóng vai Customer và nhập câu trả lời vào terminal.\n")

        # 3. Kích hoạt quá trình phỏng vấn
        # Interviewer sẽ tự động gọi hàm `chat_with_interviewer` của `Customer`
        artifact = interviewer.chat_with_customer(customer=customer, stakeholder_type="customer")

        # 4. In ra kết quả (Artifact) mà Interviewer thu thập và tổng hợp được
        print("\n=============================================")
        print("[Test Result] Cuộc phỏng vấn đã kết thúc.")
        print("[Artifact] Dữ liệu thu thập được từ Interviewer:")
        print("=============================================\n")

        print(json.dumps(artifact, indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"\n[Error] Quá trình test thất bại: {e}")


if __name__ == "__main__":
    main()