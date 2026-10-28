"""Original-worker hook for the current original send worker, never historical readback."""
from native_image_content import verify_copies
from native_image_content_driver import CopyDriver


def submitted_image_observations(task, folder, baseline_count, live, *, original_wait,
                                 pending_type, native, queue, owner_check,
                                 driver_factory=CopyDriver):
    try:
        return original_wait(task, baseline_count, live)
    except pending_type as error:
        if str(error) != 'native-ui-inline-image-not-exposed':
            raise
        expected_path = list(error.message_path)
        live()
        driver = driver_factory(folder, task, queue=queue, native=native,
                                owner_check=owner_check)
        proof = verify_copies(task, driver.read_source(), baseline_count, driver,
                              expected_path=expected_path)
        live()
        return proof['observations']
