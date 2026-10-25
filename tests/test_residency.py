"""Keeping the model in RAM between dictations. With swap in use, macOS paged Whisper's 1.6 GB of weights out during
every pause of a few minutes and the next take spent 10 to 12 s pulling them back (2026-10-25)."""

from voz import residency


class FakeMX:
    def __init__(self, active=1_618_000_000, max_rec=14_302_248_960, fail=False):
        self.active, self.max_rec, self.fail = active, max_rec, fail
        self.cleared, self.wired = 0, None

    def clear_cache(self):
        self.cleared += 1

    def get_active_memory(self):
        return self.active

    def device_info(self):
        return {"max_recommended_working_set_size": self.max_rec}

    def set_wired_limit(self, n):
        if self.fail:
            raise RuntimeError("wired limit unsupported")
        self.wired = n
        return 0


def test_wired_limit_is_the_live_weights_plus_headroom():
    assert residency.wired_limit_for(1_000, 10_000) == 1_100


def test_wired_limit_never_exceeds_what_the_system_recommends():
    assert residency.wired_limit_for(9_500, 10_000) == 10_000


def test_pin_drops_the_scratch_cache_and_wires_the_weights():
    mx = FakeMX()
    assert residency.pin(mx) == int(1_618_000_000 * 1.1)
    assert mx.cleared == 1 and mx.wired == int(1_618_000_000 * 1.1)


def test_pin_disabled_still_drops_the_scratch_but_wires_nothing():
    mx = FakeMX()
    assert residency.pin(mx, enabled=False) == 0
    assert mx.cleared == 1 and mx.wired is None


def test_pin_survives_a_machine_that_cannot_wire():
    mx = FakeMX(fail=True)
    assert residency.pin(mx) == 0          # macOS 14: the app keeps working, just without the guarantee


def test_release_scratch_clears_the_cache_and_never_raises():
    mx = FakeMX()
    residency.release_scratch(mx)
    assert mx.cleared == 1

    class Broken:
        def clear_cache(self):
            raise RuntimeError("no metal")

    residency.release_scratch(Broken())


def test_engines_follow_the_keep_model_resident_setting():
    from voz.config import Config
    from voz.engines import load_engine
    assert load_engine(Config(engine="whisper")).keep_resident is True
    assert load_engine(Config(engine="whisper", keep_model_resident=False)).keep_resident is False
    assert load_engine(Config(engine="parakeet", keep_model_resident=False)).keep_resident is False
