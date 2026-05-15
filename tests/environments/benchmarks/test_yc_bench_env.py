import importlib
import pathlib
import sqlite3
import sys
import types
from unittest import mock


class MockClass:
    pass


import pytest


def _stub_module(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _load_yc_bench_module(monkeypatch: pytest.MonkeyPatch):
    stub_modules = {
        "atroposlib": _stub_module("atroposlib"),
        "atroposlib.envs": _stub_module("atroposlib.envs"),
        "atroposlib.envs.base": _stub_module(
            "atroposlib.envs.base",
            EvalHandlingEnum=MockClass,
            BaseEnv=MockClass,
            BaseEnvConfig=MockClass,
            ScoredDataGroup=MockClass,
            ScoredDataItem=MockClass,
        ),
        "atroposlib.envs.server_handling": _stub_module(
            "atroposlib.envs.server_handling"
        ),
        "atroposlib.envs.server_handling.server_manager": _stub_module(
            "atroposlib.envs.server_handling.server_manager",
            APIServerConfig=MockClass,
            ServerBaseline=MockClass,
            ServerManager=MockClass,
        ),
        "atroposlib.envs.server_handling.openai_server": _stub_module(
            "atroposlib.envs.server_handling.openai_server",
            OpenAIServerConfig=MockClass,
        ),
        "atroposlib.type_definitions": _stub_module(
            "atroposlib.type_definitions",
            Item=MockClass,
        ),
    }

    stub_modules["atroposlib"].envs = stub_modules["atroposlib.envs"]
    stub_modules["atroposlib"].type_definitions = stub_modules[
        "atroposlib.type_definitions"
    ]
    stub_modules["atroposlib.envs"].base = stub_modules["atroposlib.envs.base"]
    stub_modules["atroposlib.envs"].server_handling = stub_modules[
        "atroposlib.envs.server_handling"
    ]
    stub_modules["atroposlib.envs.server_handling"].server_manager = stub_modules[
        "atroposlib.envs.server_handling.server_manager"
    ]
    stub_modules["atroposlib.envs.server_handling"].openai_server = stub_modules[
        "atroposlib.envs.server_handling.openai_server"
    ]

    for name, module in stub_modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    return importlib.import_module("environments.benchmarks.yc_bench.yc_bench_env")


@pytest.fixture
def read_final_score():
    module_name = "environments.benchmarks.yc_bench.yc_bench_env"

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.delitem(sys.modules, module_name, raising=False)
        yield _load_yc_bench_module(monkeypatch)._read_final_score


def test_missing_db_file(read_final_score) -> None:
    """Test behavior when the database file does not exist."""
    with mock.patch("os.path.exists", return_value=False):
        result = read_final_score("/fake/path/db.sqlite")

    assert isinstance(result, dict)
    assert type(result["final_funds_cents"]) is int
    assert type(result["survived"]) is bool
    assert type(result["terminal_reason"]) is str

    assert result["final_funds_cents"] == 0
    assert result["survived"] is False
    assert result["terminal_reason"] == "db_missing"


def test_db_read_error(tmp_path: pathlib.Path, read_final_score) -> None:
    """Test behavior when the database encounters an operational error."""
    db_file = tmp_path / "test.sqlite"
    db_file.write_text("fake db content")  # Ensure file exists to pass os.path.exists

    with mock.patch(
        "sqlite3.connect", side_effect=sqlite3.DatabaseError("Corrupted file")
    ):
        result = read_final_score(str(db_file))

    assert result["final_funds_cents"] == 0
    assert result["survived"] is False
    assert result["terminal_reason"] == "db_error: Corrupted file"


def create_mock_db(
    db_path: pathlib.Path | str,
    companies_rows: list[int] | None,
    sim_events_rows: list[tuple[str, float]] | None = None,
) -> None:
    """Helper to create a temporary DB with given rows."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE companies (funds_cents INTEGER)")
    if companies_rows is not None:
        for funds in companies_rows:
            cur.execute("INSERT INTO companies (funds_cents) VALUES (?)", (funds,))

    if sim_events_rows is not None:
        cur.execute("CREATE TABLE sim_events (event_type TEXT, scheduled_at REAL)")
        for event, sched in sim_events_rows:
            cur.execute(
                "INSERT INTO sim_events (event_type, scheduled_at) VALUES (?, ?)",
                (event, sched),
            )
    conn.commit()
    conn.close()


def test_happy_path_survived(tmp_path: pathlib.Path, read_final_score) -> None:
    """Test standard survival scenario."""
    db_file = tmp_path / "test.sqlite"
    create_mock_db(
        db_file, companies_rows=[1500000], sim_events_rows=[("horizon_end", 100.0)]
    )
    result = read_final_score(str(db_file))

    assert result["final_funds_cents"] == 1500000
    assert result["survived"] is True
    assert result["terminal_reason"] == "horizon_end"


def test_happy_path_bankrupt(tmp_path: pathlib.Path, read_final_score) -> None:
    """Test standard bankruptcy scenario."""
    db_file = tmp_path / "test.sqlite"
    create_mock_db(
        db_file, companies_rows=[-50000], sim_events_rows=[("bankruptcy", 100.0)]
    )
    result = read_final_score(str(db_file))

    assert result["final_funds_cents"] == -50000
    assert result["survived"] is False
    assert result["terminal_reason"] == "bankruptcy"


def test_boundary_funds_zero(tmp_path: pathlib.Path, read_final_score) -> None:
    """Test boundary condition where funds_cents is exactly 0."""
    db_file = tmp_path / "test.sqlite"
    create_mock_db(
        db_file, companies_rows=[0], sim_events_rows=[("horizon_end", 100.0)]
    )
    result = read_final_score(str(db_file))

    # 0 funds without bankruptcy means survival based on >= 0 logic
    assert result["final_funds_cents"] == 0
    assert result["survived"] is True
    assert result["terminal_reason"] == "horizon_end"


def test_empty_companies_table(tmp_path: pathlib.Path, read_final_score) -> None:
    """Test when the companies table exists but is empty."""
    db_file = tmp_path / "test.sqlite"
    create_mock_db(db_file, companies_rows=[], sim_events_rows=[("horizon_end", 100.0)])
    result = read_final_score(str(db_file))

    assert result["final_funds_cents"] == 0
    assert result["survived"] is True
    assert result["terminal_reason"] == "horizon_end"


def test_empty_sim_events_table(tmp_path: pathlib.Path, read_final_score) -> None:
    """Test when the sim_events table exists but is empty."""
    db_file = tmp_path / "test.sqlite"
    create_mock_db(db_file, companies_rows=[100], sim_events_rows=[])
    result = read_final_score(str(db_file))

    assert result["final_funds_cents"] == 100
    assert result["survived"] is True
    assert result["terminal_reason"] == "unknown"


def test_missing_sim_events_table(tmp_path: pathlib.Path, read_final_score) -> None:
    """Test when the sim_events table is entirely missing."""
    db_file = tmp_path / "test.sqlite"
    create_mock_db(db_file, companies_rows=[100], sim_events_rows=None)
    result = read_final_score(str(db_file))

    assert result["final_funds_cents"] == 100
    assert result["survived"] is True
    assert result["terminal_reason"] == "unknown"


def test_casing_and_whitespace_robustness(
    tmp_path: pathlib.Path, read_final_score
) -> None:
    """Test terminal_reason robust parsing for casing and whitespace."""
    db_file = tmp_path / "test.sqlite"
    create_mock_db(
        db_file, companies_rows=[100], sim_events_rows=[("\n\t BankRuptcy \t", 100.0)]
    )
    result = read_final_score(str(db_file))

    assert result["final_funds_cents"] == 100
    assert result["survived"] is False
    assert result["terminal_reason"] == "bankruptcy"


def test_return_shape(tmp_path: pathlib.Path, read_final_score) -> None:
    """Test that the return dictionary has exactly the right shape and types."""
    db_file = tmp_path / "test.sqlite"
    create_mock_db(
        db_file, companies_rows=[100], sim_events_rows=[("horizon_end", 100.0)]
    )
    result = read_final_score(str(db_file))

    # Assert exact keys
    assert set(result.keys()) == {"final_funds_cents", "survived", "terminal_reason"}

    # Assert exact types
    assert type(result["final_funds_cents"]) is int
    assert type(result["survived"]) is bool
    assert type(result["terminal_reason"]) is str
