from voz.doctor import secure_input_line


def test_doctor_explains_secure_input():
    assert secure_input_line(False, None) == "Secure keyboard input: off"
    line = secure_input_line(True, (664, "Google Chrome"))
    assert "Google Chrome" in line and "664" in line and "still pastes" in line
    assert "unknown" in secure_input_line(True, None)
