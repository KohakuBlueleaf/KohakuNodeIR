"""Data pipeline example: simulated CSV processing with branching."""

from pathlib import Path

from kohakunode import Executor


def load_csv(path):
    print(f"  [load_csv] Loading from {path}")
    return list(range(200))


def clean_data(data):
    print(f"  [clean_data] Cleaning {len(data)} rows")
    return [x for x in data if x >= 0]


def filter_outliers(data, threshold=0.5):
    print(f"  [filter_outliers] Filtering with threshold={threshold}")
    cutoff = int(len(data) * threshold)
    return data[:cutoff]


def compute_stats(data):
    mean = sum(data) / len(data) if data else 0
    std = (sum((x - mean) ** 2 for x in data) / len(data)) ** 0.5 if data else 0
    count = len(data)
    print(f"  [compute_stats] mean={mean:.1f}, std={std:.1f}, count={count}")
    return mean, std, count


def normalize(data, mean, std):
    if std == 0:
        return data
    return [(x - mean) / std for x in data]


def save_csv(data, path):
    print(f"  [save_csv] Saved {len(data)} rows to {path}")


if __name__ == "__main__":
    exe = Executor()
    exe.register("load_csv", load_csv, output_names=["data"])
    exe.register("clean_data", clean_data, output_names=["cleaned"])
    exe.register("filter_outliers", filter_outliers, output_names=["filtered"])
    exe.register("compute_stats", compute_stats, output_names=["mean", "std", "count"])
    exe.register("greater_than", lambda a, b: a > b, output_names=["result"])
    exe.register("normalize", normalize, output_names=["normalized"])
    exe.register("save_csv", save_csv, output_names=[])
    exe.register("print_val", lambda v: print(f"  {v}"), output_names=[])

    print("Running data pipeline:")
    kir_path = Path(__file__).parent / "data_pipeline.kir"
    exe.execute_file(kir_path)
