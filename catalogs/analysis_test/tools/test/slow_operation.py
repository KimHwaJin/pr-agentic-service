def slow_operation(seconds: int = 30, data=None) -> dict:
    """[시험용] 지정한 시간 동안 기다린 뒤 입력을 그대로 돌려줍니다.

    실행 대기, 진행 표시, 취소를 시험할 때만 씁니다.

    Args:
        seconds: 기다릴 시간 (초, 최대 600)
        data: 그대로 돌려줄 입력 (선택)

    Returns:
        {"slept": int, "data": object}
    """
    import time

    seconds = max(0, min(int(seconds), 600))
    for i in range(seconds):
        if i % 10 == 0:
            print(f"slow_operation: {i}/{seconds}s")
        time.sleep(1)
    print(f"slow_operation: done ({seconds}s)")
    return {"slept": seconds, "data": data}
