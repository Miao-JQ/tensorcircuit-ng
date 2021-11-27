import sys
import os
import numpy as np
import scipy
import pytest
from pytest_lazyfixture import lazy_fixture as lf


thisfile = os.path.abspath(__file__)
modulepath = os.path.dirname(os.path.dirname(thisfile))

sys.path.insert(0, modulepath)
import tensorcircuit as tc

# TODO: make everything compatible to different backends

N = 16
D = 100


def genereate_test_circuits(full):
    def reproducible_unitary(n):
        A = np.arange(n ** 2).reshape((n, n))
        A = A + np.sin(A) * 1j
        A = A - A.conj().T
        return scipy.linalg.expm(A).astype(tc.dtypestr)

    O1 = tc.gates.any(reproducible_unitary(2).reshape((2, 2)))
    O2 = tc.gates.any(reproducible_unitary(4).reshape((2, 2, 2, 2)))

    # Construct a complicated circuit by Circuit and MPSCircuit and compare

    c = tc.Circuit(N)
    c.H(0)

    if full:
        rangei = lambda j, N: range(0, N - 1)
    else:
        rangei = lambda j, N: range(j, N - 1 - j)

    # create as much correlation as possible
    for j in range(N // 2):
        for i in rangei(j, N):
            c.apply(O2.copy(), i, i + 1)
            c.apply(O1.copy(), i)
    # test non-adjacent double gates
    c.apply(O2.copy(), N // 2 - 1, N // 2 + 1)
    c.apply(O2.copy(), N // 2 - 2, N // 2 + 2)
    c.cz(2, 3)
    w_c = c.wavefunction()

    mps = tc.MPSCircuit(N)
    mps.set_truncation_rule(max_singular_values=D)
    mps.H(0)
    for j in range(N // 2):
        for i in rangei(j, N):
            mps.apply(O2.copy(), i, i + 1)
            mps.apply(O1.copy(), i)
    mps.apply(O2.copy(), N // 2 - 1, N // 2 + 1)
    mps.apply(O2.copy(), N // 2 - 2, N // 2 + 2)
    mps.cz(2, 3)
    w_mps = mps.wavefunction()

    mps_exact = tc.MPSCircuit(N)
    mps_exact.set_truncation_rule()
    mps_exact.H(0)
    for j in range(N // 2):
        for i in rangei(j, N):
            mps_exact.apply(O2.copy(), i, i + 1)
            mps_exact.apply(O1.copy(), i)
    mps_exact.apply(O2.copy(), N // 2 - 1, N // 2 + 1)
    mps_exact.apply(O2.copy(), N // 2 - 2, N // 2 + 2)
    mps_exact.cz(2, 3)
    w_mps_exact = mps_exact.wavefunction()

    return [c, w_c, mps, w_mps, mps_exact, w_mps_exact]


@pytest.fixture
def genereate_test_circuits_1():
    tc.set_dtype("complex128")
    yield genereate_test_circuits(False)
    tc.set_dtype("complex64")


@pytest.fixture
def genereate_test_circuits_2():
    tc.set_dtype("complex128")
    yield genereate_test_circuits(True)
    tc.set_dtype("complex64")


@pytest.mark.parametrize(
    "test_circuits", [lf("genereate_test_circuits_1"), lf("genereate_test_circuits_2")]
)
def test_wavefunction(test_circuits):
    # print(test_circuits)
    c, w_c, mps, w_mps, mps_exact, w_mps_exact = test_circuits  # pylint: disable=W0612
    # the wavefuntion is exact if there's no truncation
    assert np.allclose(w_mps_exact, w_c)


@pytest.mark.parametrize(
    "test_circuits, real_fedility_ref, estimated_fedility_ref",
    [
        (lf("genereate_test_circuits_1"), 0.9998648317622654, 0.9999264292512574),
        (lf("genereate_test_circuits_2"), 0.9705050538783289, 0.984959108658121),
    ],
)
def test_truncation(test_circuits, real_fedility_ref, estimated_fedility_ref):
    c, w_c, mps, w_mps, mps_exact, w_mps_exact = test_circuits  # pylint: disable=W0612
    # compare with a precalculated value
    real_fedility = np.abs(w_mps.conj().dot(w_c)) ** 2
    assert np.isclose(real_fedility, real_fedility_ref)
    estimated_fedility = mps._fidelity
    assert np.isclose(estimated_fedility, estimated_fedility_ref)


@pytest.mark.parametrize(
    "test_circuits", [lf("genereate_test_circuits_1"), lf("genereate_test_circuits_2")]
)
def test_amplitude(test_circuits):
    c, w_c, mps, w_mps, mps_exact, w_mps_exact = test_circuits  # pylint: disable=W0612
    # compare with wavefunction
    s = "01" * (N // 2)
    sint = int(s, 2)  # binary to decimal
    err_amplitude = np.abs(mps.amplitude(s) - w_mps[sint])
    assert np.isclose(err_amplitude, 0, atol=1e-12)


@pytest.mark.parametrize(
    "test_circuits", [lf("genereate_test_circuits_1"), lf("genereate_test_circuits_2")]
)
def test_expectation(test_circuits):
    c, w_c, mps, w_mps, mps_exact, w_mps_exact = test_circuits  # pylint: disable=W0612
    for site in range(N):
        exp_mps = mps_exact.expectation_single_gate(tc.gates.z(), site)
        exp_mps_general = mps_exact.general_expectation([tc.gates.z(), [site]])
        exp_c = c.expectation((tc.gates.z(), [site]), reuse=False)
        assert np.isclose(exp_mps, exp_c, atol=1e-7)
        # the general expectation of a double qubit gate would be non-exact because of truncation,
        # which could also be manually disabled (currently not implemented)
        assert np.isclose(exp_mps_general, exp_c, atol=1e-7)


@pytest.fixture
def generate_external_wavefunction():
    # create a fixed wavefunction and create the corresponding MPS
    w_external = np.abs(np.sin(np.arange(2 ** N) % np.exp(1))).astype(
        tc.dtypestr
    )  # Just want to find a function that is so strange that the correlation is strong enough
    w_external /= np.linalg.norm(w_external)
    mps_external = tc.MPSCircuit.from_wavefunction(w_external, max_singular_values=D)
    mps_external_exact = tc.MPSCircuit.from_wavefunction(w_external)
    return w_external, mps_external, mps_external_exact


def test_fromwavefunction(generate_external_wavefunction):
    (
        w_external,
        mps_external,
        mps_external_exact,
    ) = generate_external_wavefunction  # pylint: disable=W0612
    assert np.allclose(mps_external_exact.wavefunction(), w_external, atol=1e-7)
    # compare fidelity of truncation with theoretical limit obtained by SVD
    real_fedility = np.abs(mps_external.wavefunction().conj().dot(w_external)) ** 2
    s = np.linalg.svd(w_external.reshape((2 ** (N // 2), 2 ** (N // 2))))[1]
    theoretical_upper_limit = np.sum(s[0:D] ** 2)
    relative_err = np.log((1 - real_fedility) / (1 - theoretical_upper_limit))
    assert np.isclose(relative_err, 0.11, atol=1e-2)


@pytest.mark.parametrize(
    "test_circuits", [lf("genereate_test_circuits_1"), lf("genereate_test_circuits_2")]
)
def test_proj(test_circuits, generate_external_wavefunction):
    c, w_c, mps, w_mps, mps_exact, w_mps_exact = test_circuits  # pylint: disable=W0612
    (
        w_external,  # pylint: disable=W0612
        mps_external,  # pylint: disable=W0612
        mps_external_exact,  # pylint: disable=W0612
    ) = generate_external_wavefunction  # pylint: disable=W0612
    # compare projection value with wavefunction calculated results
    proj = mps.proj_with_mps(mps_external)
    proj_ref = mps_external.wavefunction().conj().dot(w_mps)
    np.isclose(proj, proj_ref, atol=1e-12)