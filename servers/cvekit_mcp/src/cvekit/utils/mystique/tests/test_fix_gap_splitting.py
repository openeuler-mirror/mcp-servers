#!/usr/bin/env python3
"""
Test the fix for gap splitting in code_by_lines.
Verifies that when a gap contains keep_lines/pre_diff_lines,
consecutive non-special lines are grouped into ONE placeholder
so that placeholder count matches hunk count.
"""

import sys
sys.path.insert(0, '/home/liping/mystique/src')
sys.path.insert(0, '/home/liping/mystique')

from src.project import Method, File, Project
from src.common import Language
from src.codefile import CodeFile
from src import config


def test_gap_with_pre_diff():
    """Simulate the exact scenario from _skcipher_recvmsg gap #5:
    - lines=32, keep_lines=[42, 53], pre_diff_lines=[40, 51]
    - gap #5: target lines 47->52, missing [48, 49, 50, 51]
    - line 51 is pre_diff, lines 48-50 are regular
    - Expected: lines 48-50 produce ONE placeholder, not THREE
    """
    code = """\
static int _skcipher_recvmsg(struct socket *sock, struct msghdr *msg,
                             size_t ignored, int flags) {
    struct sock *sk = sock->sk;
    struct alg_sock *ask = alg_sk(sk);
    struct sock *psk = ask->parent;
    struct alg_sock *pask = alg_sk(psk);
    struct af_alg_ctx *ctx = ask->private;
    struct crypto_skcipher *tfm = pask->private;
    unsigned int bs = crypto_skcipher_chunksize(tfm);
    struct af_alg_async_req *areq;
    int err = 0;
    size_t len = 0;
    if (!ctx->init || (ctx->more && ctx->used < bs)) {
        err = af_alg_wait_for_data(sk, flags, bs);
        if (err)
            return err;
    }
    /* Allocate cipher request for current operation. */
    areq = af_alg_alloc_areq(sk, sizeof(struct af_alg_async_req) +
                             crypto_skcipher_reqsize(tfm));
    if (IS_ERR(areq))
        return PTR_ERR(areq);
    /* convert iovecs of output buffers into RX SGL */
    err = af_alg_get_rsgl(sk, msg, flags, areq, ctx->used, &len);
    if (err)
        goto free;
    /*
     * If more buffers are to be expected to be processed, process only
     * full block size buffers.
     */
    if (ctx->more || len < ctx->used) {
        if (len < bs) {
            err = -EINVAL;
            goto free;
        }
        len -= len % bs;
    }
    /*
     * Create a per request TX SGL for this request which tracks the
     * SG entries from the global TX SGL.
     */
    areq->tsgl_entries = af_alg_count_tsgl(sk, len, 0);
    if (!areq->tsgl_entries)
        areq->tsgl_entries = 1;
    areq->tsgl = sock_kmalloc(sk, array_size(sizeof(*areq->tsgl),
                              areq->tsgl_entries),
                              GFP_KERNEL);
    if (!areq->tsgl) {
        err = -ENOMEM;
        goto free;
    }
    sg_init_table(areq->tsgl, areq->tsgl_entries);
    af_alg_pull_tsgl(sk, len, areq->tsgl, 0);
    /* Initialize the crypto operation */
    skcipher_request_set_tfm(&areq->cra_u.skcipher_req, tfm);
    skcipher_request_set_crypt(&areq->cra_u.skcipher_req, areq->tsgl,
                               areq->first_rsgl.sgl.sgt.sgl, len, ctx->iv);
    if (msg->msg_iocb && !is_sync_kiocb(msg->msg_iocb)) {
        /* AIO operation */
        sock_hold(sk);
        areq->iocb = msg->msg_iocb;
        /* Remember output size that will be generated. */
        areq->outlen = len;
        skcipher_request_set_callback(&areq->cra_u.skcipher_req,
                                      CRYPTO_TFM_REQ_MAY_SLEEP,
                                      af_alg_async_cb, areq);
        err = ctx->enc ?
              crypto_skcipher_encrypt(&areq->cra_u.skcipher_req) :
              crypto_skcipher_decrypt(&areq->cra_u.skcipher_req);
        /* AIO operation in progress */
        if (err == -EINPROGRESS)
            return -EIOCBQUEUED;
        sock_put(sk);
    } else {
        /* Synchronous operation */
        skcipher_request_set_callback(&areq->cra_u.skcipher_req,
                                      CRYPTO_TFM_REQ_MAY_SLEEP |
                                      CRYPTO_TFM_REQ_MAY_BACKLOG,
                                      crypto_req_done, &ctx->wait);
        err = crypto_wait_req(ctx->enc ?
                              crypto_skcipher_encrypt(&areq->cra_u.skcipher_req) :
                              crypto_skcipher_decrypt(&areq->cra_u.skcipher_req),
                              &ctx->wait);
    }
free:
    af_alg_free_resources(areq);
    return err ? err : len;
}"""

    # Create method from code
    codefile = CodeFile("test.c", code)
    project = Project("test", [codefile], Language.C)
    method = project.get_only_method()
    print(f"Method: {method.name}")
    print(f"rel_line_set count: {len(method.rel_line_set)}")
    print(f"Relative lines: {sorted(method.rel_line_set)}")

    # Reproduce the slice lines from the log
    target_slice_rel_lines = {1, 2, 12, 24, 31, 36, 37, 38, 39, 40, 41, 42, 43,
                              44, 45, 46, 47, 52, 53, 54, 55, 56, 57, 58, 60,
                              64, 65, 66, 74, 84, 87, 88}
    keep_lines = {42, 53}
    pre_diff_lines = {42, 53}  # Now properly converted to target lines

    print(f"\n=== Test 1: code_by_lines with keep_lines and pre_diff_lines ===")
    print(f"slice_lines: {len(target_slice_rel_lines)} lines")
    print(f"keep_lines: {sorted(keep_lines)}")
    print(f"pre_diff_lines: {sorted(pre_diff_lines)}")

    result = method.code_by_lines(
        target_slice_rel_lines,
        placeholder=config.PLACE_HOLDER,
        keep_lines=keep_lines,
        pre_diff_lines=pre_diff_lines,
    )

    placeholder_count = sum(
        1 for line in result.split("\n")
        if line.strip() == config.PLACE_HOLDER.strip()
    )
    print(f"\nPlaceholder count in generated code: {placeholder_count}")

    print(f"\n=== Test 2: reduced_hunks ===")
    hunks = method.reduced_hunks(target_slice_rel_lines)
    hunk_count = len(hunks)
    print(f"Hunk count from reduced_hunks: {hunk_count}")

    print(f"\n=== Result ===")
    if placeholder_count == hunk_count:
        print(f"PASS: placeholder count ({placeholder_count}) == hunk count ({hunk_count})")
        return True
    else:
        print(f"FAIL: placeholder count ({placeholder_count}) != hunk count ({hunk_count})")
        print(f"  Gap #5 should produce 1 placeholder (for lines 48-50), not 3")
        print(f"  _placeholder_line_nums groups: ", end="")
        from src import utils
        groups = utils.group_consecutive_ints(
            sorted(method._placeholder_line_nums))
        print(groups)
        return False


def test_consecutive_non_special_lines_grouped():
    """Simple test: a gap with [regular, regular, special, regular]
    should produce 2 placeholders (one per consecutive regular run)."""
    code = """\
void foo(void) {
    int a = 1;
    int b = 2;
    int c = 3;
    int d = 4;
    int e = 5;
}"""

    codefile = CodeFile("test2.c", code)
    project = Project("test2", [codefile], Language.C)
    method = project.get_only_method()

    # Include only lines 1 and 6 (signature and closing brace)
    # Gap is lines 2-5 with line 3 as keep_line
    slice_lines = {1, 6}
    keep_lines = {3}
    pre_diff_lines = set()

    print(f"\n=== Test 3: consecutive regular lines grouped ===")
    result = method.code_by_lines(
        slice_lines,
        placeholder=config.PLACE_HOLDER,
        keep_lines=keep_lines,
        pre_diff_lines=pre_diff_lines,
    )

    placeholder_count = sum(
        1 for line in result.split("\n")
        if line.strip() == config.PLACE_HOLDER.strip()
    )
    print(f"Generated code:\n{result}")
    print(f"Placeholder count: {placeholder_count}")

    # Expected: 2 placeholders (one for line 2, one for lines 4-5)
    # Line 3 is keep_line, output as actual code
    if placeholder_count == 2:
        print("PASS: 2 placeholders (one per consecutive regular run)")
        return True
    else:
        print(f"FAIL: expected 2 placeholders, got {placeholder_count}")
        return False


if __name__ == "__main__":
    all_pass = True
    all_pass &= test_consecutive_non_special_lines_grouped()
    all_pass &= test_gap_with_pre_diff()
    print(f"\n{'='*60}")
    print(f"Overall: {'PASS' if all_pass else 'FAIL'}")
    sys.exit(0 if all_pass else 1)
