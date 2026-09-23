# SPDX-License-Identifier: MIT
"""Generated standalone native component regression. No ZeroRun runtime required.

Run only in an appropriate isolated environment: EvalPlus executes the embedded
candidate. This is a pinned component handoff, not an end-to-end benchmark run.
"""
import argparse
import hashlib
import importlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import tempfile
import types

PAYLOAD = json.loads('{"capture_sha256":"1b61058386bebc5ed07e66493317c0bc6620cd3fd190445f57c254cb9039a47d","family":"swe","level":"native-component-regression","provenance":{"candidate_sha256":"10767ec508d8e6f7a0f3c2a114b3e316f75f78abd33f4f5ddf23c7c2547818a2","input_sha256":"8168b4fc316f8dd04d1f247ca1f2f9dfd47c9243fdc0648f1a950db347043f5e","source_sha256":"c891dee92350f8927abfdf8a7c5c664df7838f1c65f2ffe069f854c5ec57ff95"},"recipe":{"input":{"log":"Task Metadata:\\n\\t- Instance ID: sympy__sympy-12454\\n\\t- Testbed: /n/fs/p-swe-bench/temp/claude-2-bm25-13k-greedy/sympy__sympy/1.0/tmpurkmr27i/sympy__sympy__1.0\\n\\t- Virtual Env.: sympy__sympy__1.0\\n\\t- Evaluation Model: claude-2-bm25-13k-greedy\\n>>>>> Patch Apply Failed; (pred_try)\\nOutput:\\n/n/fs/p-swe-bench/temp/claude-2-bm25-13k-greedy/sympy__sympy/1.0/tmpurkmr27i/temp_sympy__sympy-12454_pred_try.patch:10: trailing whitespace.\\n            for j in range(upper_limit):  \\nChecking patch sympy/matrices/matrices.py...\\nerror: while searching for:\\n        if not self.rows >= self.cols:\\n            return False\\n        for i in range(1, self.rows):\\n            for j in range(i):\\n                if self[i, j]:\\n                    return False\\n        return True\\n\\nerror: patch failed: sympy/matrices/matrices.py:1109\\nerror: sympy/matrices/matrices.py: patch does not apply\\n>>>>> Patch Apply Failed; (pred_minimal_try)\\nOutput:\\nChecking patch sympy/matrices/matrices.py...\\nerror: while searching for:\\n            for j in range(i):\\n                if self[i, j]:\\n\\nerror: patch failed: sympy/matrices/matrices.py:1112\\nerror: sympy/matrices/matrices.py: patch does not apply\\n","spec":{"FAIL_TO_PASS":["test_is_upper","test_hessenberg"],"PASS_TO_PASS":["test_args","test_division","test_sum","test_addition","test_fancy_index_matrix","test_multiplication","test_power","test_creation","test_tolist","test_as_mutable","test_determinant","test_det_LU_decomposition","test_berkowitz_minors","test_slicing","test_submatrix_assignment","test_extract","test_reshape","test_applyfunc","test_expand","test_random","test_LUdecomp","test_LUsolve","test_QRsolve","test_inverse","test_matrix_inverse_mod","test_util","test_jacobian_hessian","test_QR","test_QR_non_square","test_nullspace","test_columnspace","test_wronskian","test_subs","test_xreplace","test_transpose","test_conjugate","test_conj_dirac","test_trace","test_shape","test_col_row_op","test_zip_row_op","test_issue_3950","test_issue_3981","test_evalf","test_is_symbolic","test_is_lower","test_is_nilpotent","test_zeros_ones_fill","test_empty_zeros","test_inv_iszerofunc","test_jacobian_metrics","test_jacobian2","test_issue_4564","test_nonvectorJacobian","test_vec","test_vech","test_vech_errors","test_diag","test_get_diag_blocks1","test_get_diag_blocks2","test_inv_block","test_creation_args","test_diagonal_symmetrical","test_diagonalization","test_jordan_form","test_jordan_form_complex_issue_9274","test_issue_10220","test_Matrix_berkowitz_charpoly","test_exp","test_has","test_errors","test_len","test_integrate","test_diff","test_getattr","test_cholesky","test_LDLdecomposition","test_cholesky_solve","test_LDLsolve","test_lower_triangular_solve","test_upper_triangular_solve","test_diagonal_solve","test_singular_values","test_condition_number","test_equality","test_col_join","test_row_insert","test_col_insert","test_normalized","test_print_nonzero","test_zeros_eye","test_is_zero","test_rotation_matrices","test_DeferredVector","test_DeferredVector_not_iterable","test_DeferredVector_Matrix","test_GramSchmidt","test_casoratian","test_zero_dimension_multiply","test_slice_issue_2884","test_slice_issue_3401","test_copyin","test_invertible_check","test_issue_5964","test_issue_7604","test_is_Identity","test_dot","test_dual","test_anti_symmetric","test_issue_5321","test_issue_5320","test_issue_11944","test_cross","test_hash","test_adjoint","test_simplify_immutable","test_rank","test_issue_11434","test_rank_regression_from_so","test_replace","test_replace_map","test_atoms","test_pinv_solve","test_gauss_jordan_solve","test_issue_7201","test_free_symbols","test_hermitian","test_doit","test_issue_9457_9467_9876","test_issue_9422","test_issue_10770","test_issue_10658","test_partial_pivoting","test_iszero_substitution"],"instance_id":"sympy__sympy-12454","log_parser":"parse_log_sympy","repo":"sympy/sympy","version":"1.0"}},"maintenance_action":"Preserve original-log admission and native default reporting; excluded logs cannot establish a patch-failure conclusion.","record_id":"20231010_rag_claude2|sympy__sympy-12454","reference":{"found":false,"report":{"FAIL_TO_FAIL":{"failure":[],"success":[]},"FAIL_TO_PASS":{"failure":["test_is_upper","test_hessenberg"],"success":[]},"PASS_TO_FAIL":{"failure":[],"success":[]},"PASS_TO_PASS":{"failure":["test_args","test_division","test_sum","test_addition","test_fancy_index_matrix","test_multiplication","test_power","test_creation","test_tolist","test_as_mutable","test_determinant","test_det_LU_decomposition","test_berkowitz_minors","test_slicing","test_submatrix_assignment","test_extract","test_reshape","test_applyfunc","test_expand","test_random","test_LUdecomp","test_LUsolve","test_QRsolve","test_inverse","test_matrix_inverse_mod","test_util","test_jacobian_hessian","test_QR","test_QR_non_square","test_nullspace","test_columnspace","test_wronskian","test_subs","test_xreplace","test_transpose","test_conjugate","test_conj_dirac","test_trace","test_shape","test_col_row_op","test_zip_row_op","test_issue_3950","test_issue_3981","test_evalf","test_is_symbolic","test_is_lower","test_is_nilpotent","test_zeros_ones_fill","test_empty_zeros","test_inv_iszerofunc","test_jacobian_metrics","test_jacobian2","test_issue_4564","test_nonvectorJacobian","test_vec","test_vech","test_vech_errors","test_diag","test_get_diag_blocks1","test_get_diag_blocks2","test_inv_block","test_creation_args","test_diagonal_symmetrical","test_diagonalization","test_jordan_form","test_jordan_form_complex_issue_9274","test_issue_10220","test_Matrix_berkowitz_charpoly","test_exp","test_has","test_errors","test_len","test_integrate","test_diff","test_getattr","test_cholesky","test_LDLdecomposition","test_cholesky_solve","test_LDLsolve","test_lower_triangular_solve","test_upper_triangular_solve","test_diagonal_solve","test_singular_values","test_condition_number","test_equality","test_col_join","test_row_insert","test_col_insert","test_normalized","test_print_nonzero","test_zeros_eye","test_is_zero","test_rotation_matrices","test_DeferredVector","test_DeferredVector_not_iterable","test_DeferredVector_Matrix","test_GramSchmidt","test_casoratian","test_zero_dimension_multiply","test_slice_issue_2884","test_slice_issue_3401","test_copyin","test_invertible_check","test_issue_5964","test_issue_7604","test_is_Identity","test_dot","test_dual","test_anti_symmetric","test_issue_5321","test_issue_5320","test_issue_11944","test_cross","test_hash","test_adjoint","test_simplify_immutable","test_rank","test_issue_11434","test_rank_regression_from_so","test_replace","test_replace_map","test_atoms","test_pinv_solve","test_gauss_jordan_solve","test_issue_7201","test_free_symbols","test_hermitian","test_doit","test_issue_9457_9467_9876","test_issue_9422","test_issue_10770","test_issue_10658","test_partial_pivoting","test_iszero_substitution"],"success":[]}},"resolution":"RESOLVED_NO","selected":{}},"reference_origin_sha256":"8679983887bc846e7c11cd5877b825f90ae363d3a59f516273022ba2d97b02e2","reference_sha256":"ce6524147242eaa238899e0c280946254b8321b60605e1ca408feedfc44b30cd","role":"policy-protection","schema":"zerorun-native-recipe/1","source_files":{"swebench/__init__.py":"f37d3f140dc5a597237df0f035aa4c6a2208643aa250592cbc76cacc5ef7f0b4","swebench/cli/__init__.py":"41bbc7629d8b5233d933dd1a2004440c0312d8a451b8b04e51859cb563c2abc3","swebench/cli/_datasets.py":"326d8f344d71b80abdc818bdcfafb473089842101e1bde3aa6742c85d82d013c","swebench/cli/cli.py":"027195fa8f24374bd71c3310a187557ebf9809e03fe062ed092dde5786381310","swebench/cli/dataset.py":"d825f86dee8d274e8724c010b990433bbbfeb8f56c1a05bcb5431a5ddbcc555d","swebench/cli/evaluate.py":"128eb25d568bb11e74f9b38bdb66db2ea041775af9559ce35e1c7b51eefa10ff","swebench/cli/images.py":"48ad0e59c88771acdfc2d81363640dfde84ad88c8ca61350d36fcd2acecc9a78","swebench/collect/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","swebench/collect/build_dataset.py":"035d9e33f59e3cbc325fc7ca817b6cac9feaea9288bdfc33aac42cc7c714f5a1","swebench/collect/build_dataset_ft.py":"c7d9817b6ad5c009f79c20e1e492c869116bc2f531e5094542660e594025801f","swebench/collect/build_local_datasets.py":"6d91f32aef795355befa29f76aea774ce2e75f5a8adc84ed4dfc7f5add3ec188","swebench/collect/cleanup/delete_gh_workflows.py":"ba755459ca40c43c11ccc94dbb7a792ac9b7a4d78e30e772789c716d0607a4ff","swebench/collect/cleanup/remove_envs.py":"344d9c43b4ec0fc45f2120e9ccf7db1c7ed5a0122b33c0652bad81dbcaddc2c5","swebench/collect/get_tasks_pipeline.py":"0c8cef1d04620095f8f448b391f205dd2c3fc43c3f78ff93480e11fdaf44c2a9","swebench/collect/get_top_pypi.py":"f3662bd7bd06b5d1f2b7f40c10879dedc587bd9966c868b2b11b8ba78612327e","swebench/collect/make_lite/criteria.py":"019d38ed826e124d3cb7d5dcc4da5f1ca47a539b16258eee642dc20def795ebd","swebench/collect/make_lite/make_lite.py":"b1f966c2bd4aca470ef8749a2ed0885565983cd327dddcc46674694ab17bf9b0","swebench/collect/make_repo/call_make_repo.py":"99ca9139118154a00190026774c411e603ee26a2a03f6a0880cd10ec923f6214","swebench/collect/print_pulls.py":"09a2a626e5d16f6181e70c3f4063e24acd570d1f4f029bee078b5d1764686f64","swebench/collect/utils.py":"2ce391f49a7cdc758b5eb79141d6142ec323bff848a394d1632b8024f5d11e65","swebench/constants.py":"f490961e07c0e96c183b1101812f19b81e44aecfb173a5919f2455c1778a96da","swebench/harness/__init__.py":"33ed461c70f7d4490f7986f41b19c05fd95adab2bcafd513be9dae33ce5d67c5","swebench/harness/constants/__init__.py":"356734173e0229462a97b6621fd7f296710a233b8e8930c40a95a3c21f8b6cd5","swebench/harness/docker_utils.py":"2c7bec870d5af8f439c468a019db3a4ec69be7c2f87972f32aed64aa95bf5025","swebench/harness/grading.py":"c891dee92350f8927abfdf8a7c5c664df7838f1c65f2ffe069f854c5ec57ff95","swebench/harness/log_parsers/__init__.py":"1bd246c64f7e19c6dc8a07bc65cd7dbabafc93caae04e847e0e2713e62d90bee","swebench/harness/log_parsers/c.py":"861a34ce7e596fd5d155ac15bf88acdc495ce12da13a8ae8bbdf8b07edee5e00","swebench/harness/log_parsers/go.py":"b604f1e26ddbffad22a14ec012e0235046f006abe43c88a01b13fba3f144f731","swebench/harness/log_parsers/java.py":"427b4c1e8361c1ca11461d34ec977356f3550fdc2328a78b9be394bcc5da0bdb","swebench/harness/log_parsers/javascript.py":"8d2a58a5f602777fbbad624d87955f4ee0e196ce8bff4c3decc9bd1ac3d56c22","swebench/harness/log_parsers/php.py":"c4e360a6daa5f032f0441898036db9b845d69fd45a40ca80b82ec156a6b767eb","swebench/harness/log_parsers/python.py":"cd56156414f8327221e525665ace9b184f7d73e83b272d9eb3f545fb17c2d9bc","swebench/harness/log_parsers/ruby.py":"3328c72a360fc518473382dfcf8117172ed8cbb89b7838b4c0801e5fe6547bcf","swebench/harness/log_parsers/rust.py":"1cfa511d1ee6a60a858b08aed9cc14e0b5438869173c12b16022d328d8a3c587","swebench/harness/modal_eval/__init__.py":"12dfa706b83207d00f8e1f7754040d1feb034ab075dbd90e52eca7ed2b5cde53","swebench/harness/modal_eval/run_evaluation_modal.py":"256482fab810383e08a960d932837040043d01e840f90d8a5cba55e0453d5613","swebench/harness/modal_eval/run_evaluation_modal_entrypoint.py":"266e75d0352baadb61c10bd8169fb186f708b1a3c0f9b0985135ec8acb6c5013","swebench/harness/modal_eval/utils.py":"08bcabe245d56230e45aab9fcacdf3a7a4630d511abd50d2826f04ee40376c7d","swebench/harness/remove_containers.py":"630f35a1c16bb0cd5fb7e708ec9d2c6ec8ce301a9ed9c7ec1d89b7ed56dc84e9","swebench/harness/reporting.py":"d1a3ce73ace1d43bce074575a386ad3143c032a0335bbc29087253c37d007fee","swebench/harness/run_evaluation.py":"0f214f7a578d1c40126fc5c5284c405505fe6d5ba07785d6e2dc06b8e2052ec1","swebench/harness/utils.py":"fc3af325c68ca4232ea2e3d16ece027bb66bb800ff4d8e3d200e622a5fd35551","swebench/image_builder/__init__.py":"325c78465e3b676ed03482d013655b964873fdd61bc46b8784f3007b3b36eec0","swebench/image_builder/constants/__init__.py":"5c7ef833bc2d6bcf50dde4de17a8c76534934b5addf4b5af308d2aa027a19da3","swebench/image_builder/docker_build.py":"a714258285dde41eb9f42b14f6eb68e00c81098a96ce02de64b6449df180c5dd","swebench/image_builder/docker_utils.py":"531ca159311dccadc7a5c38785c8d7ec95bd083d195f3840a074dff8d524860a","swebench/image_builder/image_spec.py":"e4e5da6a2c2882991f2d17757702d96f493d2910e5890857834e000cf88074b7","swebench/image_builder/prepare_images.py":"21f6934fe29181a78e2a3bc23e56d72e6d1041b5c17cf9b0e76c944f5285a8ab","swebench/inference/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","swebench/inference/llamao/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","swebench/inference/llamao/distributed_attention.py":"f70a1dfbedadc50bddc771a0ce1f72e876d5242f940bfe11363d8afbd88d0680","swebench/inference/llamao/modeling_flash_llama.py":"e526ca1456d66c5d238d73adb22dc3f562bfc546f7b38332d3f2ccd9f680ffd5","swebench/inference/make_datasets/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","swebench/inference/make_datasets/bm25_retrieval.py":"7225665c01c3238450f5af8123ea02684b6c92a05dac34844077b06f7e7ada46","swebench/inference/make_datasets/create_instance.py":"4e91747bdba29b4931b1220fbe88ceaadf9fa8e46a23a343b508f7e6749d3bf6","swebench/inference/make_datasets/create_text_dataset.py":"d2ed0d0371bc99af1d653004a1f87fba27bfc8ee289b5482645feaaa738da261","swebench/inference/make_datasets/eval_retrieval.py":"be73a91ed6c3ae78cfe0b202fe76382689286fa0119ca1a03eaa47e8d5a6e6cd","swebench/inference/make_datasets/tokenize_dataset.py":"d867a7aef979b5e07ff11dd6fd05c52bb9553f64ad6a0308a9bd3a2fbbdf5b69","swebench/inference/make_datasets/utils.py":"3d5263c2ed851c6199a5af8481e1e51e7a8a6e476177176fb09ebc5df5c7f0a6","swebench/inference/run_api.py":"09ea444a0cbb7990569ec0ac67533b986d232b9c444f8232929cda5244d5fe43","swebench/inference/run_live.py":"9115fa213850e199e6df16778ebbfa529b5d3c725c12d36184582f0c2c9c3d21","swebench/inference/run_llama.py":"b7a4e12f2e2eb67144a187a5a6aae0ee6eb9d002a6978bcdfcb80f8539706d60","swebench/logger.py":"c0286d3de68cfa1ff8b816211840e3ba698dda463e0de6f73eef9ea8fe26cde8","swebench/resources/__init__.py":"56dac1a3dc3816e1c52cab148702580e914fa629b5f2ca8feecbb6a9dcefd1e1","swebench/types.py":"7602c38a45bfd11b56d11e264a255e312ca780dd537adcd9810c1f7569abae11","swebench/utils.py":"9888a97bded2df810c466a5c660e71105780cefd1cb8c42d7f7833f2af7ee016","swebench/versioning/__init__.py":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","swebench/versioning/constants.py":"b4fd67a8f37e8d96c1cc902c5ba0c02b185838719d111be21f903817d7e8d081","swebench/versioning/extract_web/get_versions_astropy.py":"cc16b08e2f8edb022b3dd6a95fdc66aa99ec06bac86e2dc2e4c225bf0e5a19c7","swebench/versioning/extract_web/get_versions_matplotlib.py":"c96718637cecdadee213fce1a1850760cd0306cbdbedf2e07bbc3bcf9bda7f19","swebench/versioning/extract_web/get_versions_pvlib-python.py":"28fa3094613f7be45f73d7931d6ed773d74219dd8d832420e5fc54f84e9bc08a","swebench/versioning/extract_web/get_versions_pydicom.py":"f85eead435ffa4deda8c49c8768f6ff43d092767dc2e0273862a6691eb8c76a2","swebench/versioning/extract_web/get_versions_sqlfluff.py":"5b5177d5efff06d746afe151f90766147e67f42531bf77b3e539e36e238e8002","swebench/versioning/extract_web/get_versions_xarray.py":"39f11d8ed078f59c1f432afa40e82a95a6286623c369682a68c4f3e90a5f156b","swebench/versioning/get_versions.py":"78853ad359147cc2690c12173b57b4ba56df244f38f3d23668217194b017ffb0","swebench/versioning/utils.py":"d1ac6a4a0cdd1d3aede53549184d4a70e4e4c37f4432d72308f5d810b037ba6c"}},"record_sha256":"bc1cef426a94bace8a2c3c63026d4f378888a29015d0bf049d4c3309a8217c01","schema":"zerorun-native-handoff/1","template_sha256":"dc9ebcfcb7f4c7967bf6b5e47d8793d2e187cc678f8c28c7d29899cb32deaaba"}')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def execute(source, verified):
    recipe = PAYLOAD["recipe"]
    inventory = recipe["source_files"]
    prefix = "evalplus" if PAYLOAD["family"] == "evalplus" else "swebench"
    actual = {p.relative_to(source).as_posix() for p in (source/prefix).rglob("*.py")}
    if actual != set(inventory):
        raise ValueError("Native Python source inventory mismatch")
    for relative, expected in inventory.items():
        p = source/relative
        data = p.read_bytes()
        if not p.resolve().is_relative_to(source) or p.is_symlink() or sha(data) != expected:
            raise ValueError("Native source identity mismatch: " + relative)
        destination = verified/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(data)
    # Import only copied verified source: stale or poisoned bytecode is excluded.
    source = verified
    sys.dont_write_bytecode = True
    if sha(encoded(recipe["reference"])) != recipe["reference_sha256"]:
        raise ValueError("Native reference identity mismatch")
    inp = recipe["input"]
    if sys.flags.optimize != 0:
        raise ValueError("Optimized native execution is unsupported")
    if PAYLOAD["family"] == "swe":
        if sha(inp["log"].encode("utf-8")) != PAYLOAD["provenance"]["input_sha256"]:
            raise ValueError("Native input identity mismatch")
        # Bypass unrelated package-root Docker setup; native components unchanged.
        for name, rel in [("swebench", "swebench"), ("swebench.harness", "swebench/harness")]:
            module = types.ModuleType(name)
            module.__path__ = [str(source/rel)]
            sys.modules[name] = module
        native = importlib.import_module("swebench.harness.grading")
        native_types = importlib.import_module("swebench.types")
        spec = native_types.TestSpec(**inp["spec"], image="component-only", eval_script_list=[], eval_type="pass_and_fail")
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder)/"log.txt"
            log.write_bytes(inp["log"].encode("utf-8"))
            selected, found = native.get_logs_eval(spec, str(log))
        report = native.get_eval_tests_report(selected, {k:inp["spec"][k] for k in ("FAIL_TO_PASS", "PASS_TO_PASS")})
        resolution = native.get_resolution_status(report)
        result = {"selected":selected, "found":found, "report":report, "resolution":resolution}
        calls = {"native_component_entry_calls":3, "authored_candidate_bank_calls":0}
    else:
        if sha(inp["code"].encode("utf-8")) != PAYLOAD["provenance"]["candidate_sha256"] or sha(encoded(inp["inputs"])) != PAYLOAD["provenance"]["input_sha256"]:
            raise ValueError("Native candidate or input identity mismatch")
        if sys.platform != "linux" or "fork" not in mp.get_all_start_methods():
            raise ValueError("Native worker regression requires qualified Linux fork")
        sys.path.insert(0,str(source))
        native = importlib.import_module("evalplus.eval")
        ctx = mp.get_context("fork")
        stat, progress = ctx.Value("i",native._UNKNOWN), ctx.Value("i",0)
        details = ctx.Array("b",[False]*len(inp["inputs"]))
        proc = ctx.Process(target=native.unsafe_execute, kwargs={**inp,"stat":stat,"progress":progress,"details":details})
        proc.start()
        try:
            proc.join(sum(inp["time_limits"])+5)
            if proc.is_alive():
                raise RuntimeError("Native outer timeout; no qualified assertion")
            if proc.exitcode != 0 or stat.value not in (native._SUCCESS,native._FAILED):
                raise RuntimeError("Incomplete native worker; no qualified assertion")
            result = {"worker_status":stat.value,"progress":progress.value,"details":[bool(v) for v in details[:]]}
        finally:
            if proc.is_alive():
                proc.kill()
                proc.join(5)
        calls = {"native_component_entry_calls":0, "authored_candidate_bank_calls":1}
    # Type-preserving comparison: e.g. false must never equal integer zero.
    matches = encoded(result) == encoded(recipe["reference"])
    return {"result":"PASS" if matches else "FAIL", "native":result,
            "reference":recipe["reference"], "calls":calls,
            "native_module":str(Path(native.__file__).resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    # Reserve output before any native call; never rerun merely to overwrite it.
    try:
        stream = args.output.open("x",encoding="utf-8",newline="\n")
    except OSError as exc:
        print(str(exc),file=sys.stderr)
        return 2
    with stream:
        result = {"schema":"zerorun-native-regression-result/1", "level":PAYLOAD["level"],
                  "role":PAYLOAD["recipe"]["role"], "payload_sha256":sha(encoded(PAYLOAD)),
                  "python":sys.version, "optimize":sys.flags.optimize,
                  "uid":os.getuid() if hasattr(os,"getuid") else None,
                  "classification_dependency":False}
        try:
            with tempfile.TemporaryDirectory() as directory:
                result.update(execute(args.source.resolve(),Path(directory)))
            code = 0 if result["result"] == "PASS" else 1
        except Exception as exc:
            result.update(result="UNASSESSABLE",error=type(exc).__name__+": "+str(exc))
            code = 2
        json.dump(result,stream,indent=2,allow_nan=False)
        stream.write("\n")
    print(json.dumps({"result":result["result"],"output":str(args.output)}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
