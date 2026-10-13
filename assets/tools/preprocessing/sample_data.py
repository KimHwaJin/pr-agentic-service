def sample_data(data, sample_size: int = 1000, method: str = "random", seed: int = 42) -> dict:
    """분석용 표본을 추출합니다.

    Args:
        data: 입력 DataFrame
        sample_size: 표본 행 수
        method: 추출 방식 ("random" 또는 "head")
        seed: 난수 시드

    Returns:
        {"sampled_data": pandas.DataFrame, "shape": list}
    """
    size = min(int(sample_size), len(data))
    sampled = data.sample(n=size, random_state=seed) if method == "random" else data.head(size)
    print(f"sample_data: {len(data)} -> {len(sampled)} rows ({method})")
    return {"sampled_data": sampled, "shape": list(sampled.shape)}
