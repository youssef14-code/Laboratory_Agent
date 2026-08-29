import os
import sys

from app import app as flask_app  # تطبيق الفلاسك للـ DB context
from graph.agent_response import AgentResponse
from graph.graph import get_agent_graph
from software_service.client_services import ClientService


def main():
    print("=" * 65)
    print("🏥 بدء تشغيل المساعد الطبي (متصل بقاعدة البيانات + Debug Info)")
    print("💡 اكتب رسالتك واضغط Enter. للخروج اكتب: exit أو خروج")
    print("=" * 65)

    graph = get_agent_graph()

    with flask_app.app_context():

        sender_id = "test_user_terminal_1"
        page_id = "test_page_101"
        platform_id = 1

        # جلب أو إنشاء العميل وقراءة الذاكرة السابقة إن وجدت
        client, _ = ClientService.get_or_create_client(sender_id, page_id, platform_id)

        state = {
            "page_id": page_id,
            "sender_id": sender_id,
            "platform_id": platform_id,
            "platform_name": "Terminal",
            "laboratory_id": 1,
            "branch_id": 1,
            "user_message": "",
            "summary": client.summary if client else "",
            "last_bot_message": client.last_bot_message if client else "",
        }

        if state["summary"]:
            print(f"📖 تم استرجاع ذاكرة سابقة من الداتابيز:\n{state['summary']}\n")

        while True:
            try:
                user_input = input("\n👤 أنت: ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ["exit", "quit", "q", "خروج"]:
                    print("\n👋 تم إنهاء المحادثة بنجاح.")
                    break

                state["user_message"] = user_input
                print("⏳ جاري المعالجة...")

                # استدعاء الـ Graph
                result = graph.invoke(state)

                # تحديث الذاكرة محلياً
                state["summary"] = result.get("summary") or state.get("summary") or ""
                state["last_bot_message"] = result.get("last_bot_message") or result.get("response") or ""

                # تحويل النتيجة لـ AgentResponse لحساب التوكنز
                response_obj = AgentResponse.from_result(result)

                # 1. طباعة الرد
                print("\n" + "─" * 45)
                print(f"🤖 البوت:\n{response_obj.response}")
                print("─" * 45)

                # 2. طباعة النية (Intent)
                print(f"🧭 النية المكتشفة (Intent): {response_obj.intent}")

                # 3. طباعة حالات الحفظ (Flags)
                if response_obj.visit_saved:
                    print(f"🎉 تم تأكيد وحفظ الحجز! كود المرجع: {response_obj.visit_reference}")
                if response_obj.complaint_saved:
                    print("📝 تم تسجيل الشكوى بنجاح في قاعدة البيانات!")
                if response_obj.inquiry_saved:
                    print("🔍 تم حفظ وتحديث ملخص الاستفسار في قاعدة البيانات.")

                # 4. طباعة الذاكرة الحالية (Summary)
                if state["summary"]:
                    print(f"\n🧠 ملخص الذاكرة (Memory Summary):\n{state['summary']}")

                # 5. طباعة استهلاك التوكنز
                if response_obj.usage:
                    total_tokens = sum(
                        v.get("total_tokens", 0) for v in response_obj.usage.values() if isinstance(v, dict)
                    )
                    if total_tokens > 0:
                        print(f"\n⚡ إجمالي التوكنز المستهلكة في هذه الدورة: {total_tokens}")

            except KeyboardInterrupt:
                print("\n👋 تم الإلغاء.")
                break
            except Exception as e:
                print(f"\n❌ حدث خطأ: {e}")
                import traceback
                traceback.print_exc()


if __name__ == "__main__":
    main()