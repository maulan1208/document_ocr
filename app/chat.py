import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def request_json(url: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )

    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("detail")
        except (json.JSONDecodeError, UnicodeDecodeError):
            detail = None
        raise RuntimeError(
            detail or f"API trả về HTTP {error.code}."
        ) from error
    except URLError as error:
        raise RuntimeError(
            f"Không kết nối được tới server ({error.reason}). "
            "Hãy chạy Uvicorn trước."
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chat trên terminal với toàn bộ tài liệu đã xử lý."
    )
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:8000",
        help="Địa chỉ API Uvicorn (mặc định: http://127.0.0.1:8000).",
    )
    args = parser.parse_args()
    base_url = args.server_url.rstrip("/")

    try:
        request_json(f"{base_url}/health")
    except RuntimeError as error:
        parser.error(str(error))

    history: list[dict[str, str]] = []
    print("Chat với toàn bộ tài liệu. Nhập 'exit' hoặc 'quit' để thoát.")

    while True:
        try:
            message = input("\nBạn: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nĐã kết thúc phiên chat.")
            break

        if message.lower() in {"exit", "quit"}:
            print("Đã kết thúc phiên chat.")
            break
        if not message:
            continue

        try:
            result = request_json(
                f"{base_url}/chat",
                {
                    "message": message,
                    "history": history[-10:],
                },
            )
        except RuntimeError as error:
            print(f"Lỗi: {error}")
            continue

        print(f"\nTrợ lý: {result['reply']}")
        sources = result.get("sources", [])
        if sources:
            print("Nguồn:")
            for source in sources:
                print(f"- {source['filename']} (ID {source['id']})")

        history.extend(
            [
                {"role": "user", "content": message},
                {"role": "assistant", "content": result["reply"]},
            ]
        )
        history = history[-10:]

if __name__ == "__main__":
    main()
