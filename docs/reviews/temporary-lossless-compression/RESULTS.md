# Recorded synthetic result

Zstandard level 1 stored the three exact SQLite containers in **58,581 bytes**, versus **245,760 original bytes**: **76.16% fewer payload bytes**. Gzip level 9 saved 74.34% and the fixed LZ4 profile saved 64.89%. All 35 operations restored the exact input length and SHA-256. All SQLite/JSONL evidence, availability and selected references passed their separate complete checks.

**This is a small synthetic correctness smoke, with one observation per arm.** It contains zero real specimens. Both requested five-repetition attempts were deferred by the workload gate. These results establish fixture density and prototype preservation; they do not establish eligible real-drive savings, acceptable production read latency or a fastest codec.

## Run and environment

- Frozen product base: `dcf7ccbb178cdd89175e427962dec80475620c73`; exact study/product/dependency file hashes are in [synthetic-results.json](synthetic-results.json).
- UTC interval: 2026-10-05T14:37:08.428726+00:00 to 2026-10-05T14:39:34.399632+00:00.
- Seven representation inputs, 445,507 combined uncompressed bytes: three finalized SQLite files, their three separate canonical JSONL exports, and one seeded raw random file. The two representations duplicate the same 72 evidence records, not 144 independent records.
- Preparation: 68.632 s; codec/read phase: 76.984 s; whole supervised run: 149.125 s. The phase was bounded to 300 s and each child to 60 s.
- Seed 20261005; randomized order within the single repetition; 35 operations completed, zero failures. Each per-arm median/min/max is the same single observation, not the planned five-repeat distribution.
- No cache clearing. First-observed study reads follow fixture creation, hashing and correctness checks; later arm reads are warm observations. Neither is controlled cold-cache evidence.
- Start observation: qualification, 1 unclassified resident model runtime(s); quiet window false. This point-in-time classification does not prove an active inference request. No model call was made by this lane.

| Dependency/runtime | Observed version |
| --- | --- |
| python | 3.12.10 |
| architecture | AMD64 |
| pointer_bits | 64 |
| os | Windows |
| zlib_build | 1.3.1 |
| zlib_runtime | 1.3.1 |
| sqlite | 3.49.1 |
| zstandard | 0.25.0 |
| lz4 | 4.3.3 |
| psutil | 7.0.0 |
| pydantic | 2.13.4 |
| pytest | 8.4.2 |
| ruff | 0.16.9 |
| mypy | 2.3.1 |
| zstd_native | 1.5.7 |
| zstd_backend | cext |
| lz4_native | 1.9.4 |

Profiles are gzip level 9 with fixed study filename/mtime, single-thread Zstandard levels 1/3 (`threads=0`, no codec worker threads, checksum/content size), and LZ4 frame level 0 with linked 64-KiB blocks and explicit content/block checksums. Complete parameters are under `profiles`; no dictionary or extreme setting was used.

## Frozen specimen identities

| Fixture | Representation | Bytes | Records | SHA-256 |
| --- | --- | ---: | ---: | --- |
| repeated | sqlite | 65,536 | 24 | `0fb873b3fd435f7abc89b6c2592b02177a13ae679fe9e9cddfdc32b080e15d4b` |
| repeated | jsonl | 38,593 | 24 | `0842e44c9baace9cf4e8e7a46022cf7d06ccc37909cabc671bfa9b76bc50de08` |
| mixed | sqlite | 65,536 | 24 | `4f61690b062fff337b1023a9e08640950bb93094bdc43548795ec8d6843f2d05` |
| mixed | jsonl | 35,521 | 24 | `7022a1b711d205849d17b1d60274a78008add6f17e11e5fc1817b37405313ba6` |
| noisy | sqlite | 114,688 | 24 | `2cc76a42f3820984f3c97f693c67664f74dc21dd1df03bf91d2b146b72cc6e9b` |
| noisy | jsonl | 60,097 | 24 | `0ffcc566af9289b5eeb982af7d2178cc007ef55cfeb0e9793d12bee4294ee094` |
| incompressible | raw | 65,536 | n/a | `c7adbc955cc6a7b59269ecdbea604ce60d51c1bb91542aea3f1679c314fa707a` |

These are generated, disposable inputs. The public synthetic packet records schema/count, complete ordered raw-record and availability signatures, and exact reference selections; raw fixture files are retained privately. No checkpoint, vacuum, page stripping or body normalization contributed to container savings. JSONL uses the retained owner's complete object representation and native Windows CRLF newlines; an actual owner archive is checked byte-for-byte in the focused tests.

## A. Identical SQLite-container bytes

| Fixture | Arm | Input bytes | Output bytes | Output/input ratio | Reduction | Payload allocation bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| mixed | none | 65,536 | 65,536 | 1.000000 | 0.000% | 65,536 |
| mixed | gzip-9 | 65,536 | 18,128 | 0.276611 | 72.339% | 20,480 |
| mixed | zstd-1 | 65,536 | 15,534 | 0.237030 | 76.297% | 16,384 |
| mixed | zstd-3 | 65,536 | 15,644 | 0.238708 | 76.129% | 16,384 |
| mixed | lz4-frame | 65,536 | 28,420 | 0.433655 | 56.635% | 28,672 |
| noisy | none | 114,688 | 114,688 | 1.000000 | 0.000% | 114,688 |
| noisy | gzip-9 | 114,688 | 41,678 | 0.363403 | 63.660% | 45,056 |
| noisy | zstd-1 | 114,688 | 40,575 | 0.353786 | 64.621% | 40,960 |
| noisy | zstd-3 | 114,688 | 40,625 | 0.354222 | 64.578% | 40,960 |
| noisy | lz4-frame | 114,688 | 54,118 | 0.471872 | 52.813% | 57,344 |
| repeated | none | 65,536 | 65,536 | 1.000000 | 0.000% | 65,536 |
| repeated | gzip-9 | 65,536 | 3,257 | 0.049698 | 95.030% | 4,096 |
| repeated | zstd-1 | 65,536 | 2,472 | 0.037720 | 96.228% | 4,096 |
| repeated | zstd-3 | 65,536 | 2,419 | 0.036911 | 96.309% | 4,096 |
| repeated | lz4-frame | 65,536 | 3,738 | 0.057037 | 94.296% | 4,096 |

## B. Identical existing-archive JSONL bytes

| Fixture | Arm | Input bytes | Output bytes | Output/input ratio | Reduction | Payload allocation bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| mixed | none | 35,521 | 35,521 | 1.000000 | 0.000% | 36,864 |
| mixed | gzip-9 | 35,521 | 16,428 | 0.462487 | 53.751% | 20,480 |
| mixed | zstd-1 | 35,521 | 14,136 | 0.397962 | 60.204% | 16,384 |
| mixed | zstd-3 | 35,521 | 14,235 | 0.400749 | 59.925% | 16,384 |
| mixed | lz4-frame | 35,521 | 27,659 | 0.778666 | 22.133% | 28,672 |
| noisy | none | 60,097 | 60,097 | 1.000000 | 0.000% | 61,440 |
| noisy | gzip-9 | 60,097 | 39,455 | 0.656522 | 34.348% | 40,960 |
| noisy | zstd-1 | 60,097 | 38,953 | 0.648169 | 35.183% | 40,960 |
| noisy | zstd-3 | 60,097 | 39,112 | 0.650815 | 34.919% | 40,960 |
| noisy | lz4-frame | 60,097 | 52,277 | 0.869877 | 13.012% | 53,248 |
| repeated | none | 38,593 | 38,593 | 1.000000 | 0.000% | 40,960 |
| repeated | gzip-9 | 38,593 | 1,892 | 0.049024 | 95.098% | 4,096 |
| repeated | zstd-1 | 38,593 | 1,575 | 0.040811 | 95.919% | 4,096 |
| repeated | zstd-3 | 38,593 | 1,579 | 0.040914 | 95.909% | 4,096 |
| repeated | lz4-frame | 38,593 | 2,774 | 0.071878 | 92.812% | 4,096 |

## C. Deliberately incompressible bytes

| Fixture | Arm | Input bytes | Output bytes | Output/input ratio | Reduction | Payload allocation bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| incompressible | none | 65,536 | 65,536 | 1.000000 | 0.000% | 65,536 |
| incompressible | gzip-9 | 65,536 | 65,609 | 1.001114 | -0.111% | 69,632 |
| incompressible | zstd-1 | 65,536 | 65,550 | 1.000214 | -0.021% | 69,632 |
| incompressible | zstd-3 | 65,536 | 65,550 | 1.000214 | -0.021% | 69,632 |
| incompressible | lz4-frame | 65,536 | 65,567 | 1.000473 | -0.047% | 69,632 |

For JSONL alone, gzip produces 57,775 bytes and Zstandard level 1 produces 54,664 bytes: **5.38% additional payload savings relative to gzip**. That is an archive-codec comparison, not a temporary-tier reduction. Exporting SQLite to JSONL changes layout and is not byte-preserving compression of the SQLite file.

All compressed arms enlarge the 65,536-byte random fixture: gzip +73 bytes, Zstandard +14 bytes, LZ4 +31 bytes. Each crosses an NTFS allocation boundary to 69,632 payload-allocation bytes before metadata. A later owner needs a verified no-benefit decision rather than assuming every segment shrinks.

## Payload, metadata, allocation and quota basis

| Representation / arm (three evidence fixtures) | Original logical bytes | Encoded payload bytes | Payload + manifest + claim logical bytes | Original data-stream allocation | Published payload + manifest + claim allocation |
| --- | ---: | ---: | ---: | ---: | ---: |
| sqlite / none | 245,760 | 245,760 | 246,680 | 245,760 | 246,720 |
| sqlite / gzip-9 | 245,760 | 63,063 | 64,440 | 245,760 | 71,048 |
| sqlite / zstd-1 | 245,760 | 58,581 | 59,973 | 245,760 | 62,856 |
| sqlite / zstd-3 | 245,760 | 58,688 | 60,080 | 245,760 | 62,856 |
| sqlite / lz4-frame | 245,760 | 86,276 | 87,656 | 245,760 | 91,528 |
| jsonl / none | 134,211 | 134,211 | 135,129 | 139,264 | 140,224 |
| jsonl / gzip-9 | 134,211 | 57,775 | 59,151 | 139,264 | 66,952 |
| jsonl / zstd-1 | 134,211 | 54,664 | 56,055 | 139,264 | 62,856 |
| jsonl / zstd-3 | 134,211 | 54,926 | 56,317 | 139,264 | 62,856 |
| jsonl / lz4-frame | 134,211 | 82,710 | 84,089 | 139,264 | 87,432 |

For SQLite/Zstandard level 1, the prototype's logical replacement total is 59,973 bytes (75.60% below bare originals); reported stream allocation including metadata/claims is 62,856 bytes (74.42% below original streams). This is a fixture replacement calculation. **The originals remain present and no replacement occurred.**

Allocation comes from Windows `FILE_STANDARD_INFO.AllocationSize`, independently of file length. Tiny manifests report resident stream allocations of 312 or 464 bytes; one-byte claims report 8 allocated bytes. Additional MFT records, directories, the operating index and volume metadata are outside this measurement. These are not complete volume-allocation deltas. The earliest pilot's `GetCompressedFileSizeW` fields are discarded.

The logical replacement column adds every prototype payload, manifest and claim using file lengths. It describes the existing owner's accounting basis, not an admission integration: this prototype is outside that owner and its directory layout is not charged through operating `_bytes`. A future owner must charge its actual index/metadata and all partial/restore files through authoritative accounting. The uncompressed prototype control has metadata overhead; direct original reads are the read baseline.

A safe transition temporarily needs original + compressed payload + full verification/decoder copy + durable metadata/index headroom. Existing temporary/retained overlap remains additional. An archive-only codec switch cannot remove temporary SQLite. Every operating quota delta and actual reclaimed-byte count in this lane is **zero**. Cached operating totals provide no eligible denominator; no 400-GB extrapolation is justified.

## Read and resource observations

SQLite direct reads open the original and fetch exact first/middle/last/seeded-random references plus a small range. Reopen validates the encoded artifact, fully restores/fsyncs the entire segment, verifies restored length/hash, then opens SQLite and reads that selection. One reference can require full-segment restoration. Publication's full integrity/evidence check is separate from this interval.

JSONL direct and restored reads both perform complete evidence verification plus a selection scan. Restore adds encoded-artifact verification and a full fsynced copy. Its two-pass verification/scan is stronger than the existing owner's early-exit retained reader and is not a claimed faster production-equivalent implementation.

| Fixture / representation | Arm | Direct read ms | Verified restore + read ms | Compress elapsed / CPU ms | Restore elapsed / CPU ms | Peak working set / commit MiB | Peak prototype staging bytes / allocation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mixed / jsonl | none | 4.558 | 151.371 | 115.143 / 15.625 | 135.295 / 0.000 | 33.141 / 22.785 | 71,347 / 74,040 |
| mixed / jsonl | gzip-9 | 1.688 | 151.464 | 105.580 / 0.000 | 122.736 / 0.000 | 33.445 / 23.012 | 52,407 / 57,808 |
| mixed / jsonl | zstd-1 | 1.859 | 149.613 | 241.844 / 0.000 | 131.648 / 15.625 | 33.207 / 22.965 | 50,120 / 53,712 |
| mixed / jsonl | zstd-3 | 1.661 | 138.291 | 107.171 / 0.000 | 123.268 / 0.000 | 34.215 / 23.363 | 50,219 / 53,712 |
| mixed / jsonl | lz4-frame | 1.687 | 178.553 | 133.316 / 0.000 | 126.575 / 0.000 | 33.172 / 22.781 | 63,639 / 66,000 |
| noisy / jsonl | none | 4.713 | 152.466 | 118.675 / 15.625 | 137.592 / 0.000 | 33.312 / 22.492 | 120,499 / 123,192 |
| noisy / jsonl | gzip-9 | 2.907 | 209.248 | 136.988 / 0.000 | 150.269 / 0.000 | 33.570 / 22.809 | 100,010 / 102,864 |
| noisy / jsonl | zstd-1 | 2.198 | 151.156 | 123.305 / 0.000 | 135.910 / 0.000 | 33.387 / 22.988 | 99,513 / 102,864 |
| noisy / jsonl | zstd-3 | 2.313 | 168.232 | 129.708 / 0.000 | 128.839 / 0.000 | 33.859 / 23.316 | 99,672 / 102,864 |
| noisy / jsonl | lz4-frame | 2.325 | 161.858 | 128.385 / 0.000 | 144.007 / 0.000 | 33.840 / 22.887 | 112,833 / 115,152 |
| repeated / jsonl | none | 2.384 | 173.378 | 115.984 / 0.000 | 142.726 / 15.625 | 33.250 / 22.488 | 77,491 / 82,232 |
| repeated / jsonl | gzip-9 | 1.921 | 149.568 | 141.649 / 0.000 | 125.089 / 0.000 | 33.398 / 22.582 | 40,942 / 45,520 |
| repeated / jsonl | zstd-1 | 2.078 | 169.527 | 120.406 / 0.000 | 151.907 / 0.000 | 33.785 / 22.992 | 40,630 / 45,520 |
| repeated / jsonl | zstd-3 | 2.246 | 162.990 | 122.348 / 0.000 | 140.249 / 0.000 | 34.180 / 23.727 | 40,634 / 45,520 |
| repeated / jsonl | lz4-frame | 1.779 | 283.337 | 154.656 / 0.000 | 259.972 / 15.625 | 33.172 / 22.523 | 41,825 / 45,520 |
| incompressible / raw | none | n/a | 152.634 | 116.748 / 0.000 | 134.675 / 0.000 | 33.320 / 23.016 | 131,377 / 131,384 |
| incompressible / raw | gzip-9 | n/a | 127.772 | 116.799 / 15.625 | 123.890 / 0.000 | 33.445 / 22.609 | 131,603 / 135,632 |
| incompressible / raw | zstd-1 | n/a | 140.207 | 139.192 / 15.625 | 135.974 / 15.625 | 33.734 / 23.297 | 131,549 / 135,632 |
| incompressible / raw | zstd-3 | n/a | 140.533 | 160.672 / 0.000 | 138.331 / 0.000 | 33.988 / 23.707 | 131,549 / 135,632 |
| incompressible / raw | lz4-frame | n/a | 127.500 | 133.804 / 15.625 | 125.291 / 0.000 | 33.574 / 22.930 | 131,562 / 135,632 |
| mixed / sqlite | none | 2.269 | 146.567 | 143.388 / 0.000 | 137.385 / 0.000 | 34.141 / 22.605 | 131,377 / 131,384 |
| mixed / sqlite | gzip-9 | 1.903 | 142.908 | 127.452 / 0.000 | 138.225 / 0.000 | 33.488 / 22.531 | 84,122 / 86,480 |
| mixed / sqlite | zstd-1 | 1.854 | 121.363 | 94.456 / 0.000 | 113.311 / 0.000 | 33.809 / 22.738 | 81,533 / 82,384 |
| mixed / sqlite | zstd-3 | 1.816 | 168.426 | 221.994 / 0.000 | 152.399 / 0.000 | 34.625 / 23.754 | 81,643 / 82,384 |
| mixed / sqlite | lz4-frame | 1.814 | 124.413 | 127.493 / 15.625 | 117.440 / 0.000 | 34.371 / 22.883 | 94,415 / 94,672 |
| noisy / sqlite | none | 1.930 | 132.085 | 107.999 / 0.000 | 124.733 / 0.000 | 33.414 / 22.430 | 229,683 / 229,688 |
| noisy / sqlite | gzip-9 | 3.349 | 156.299 | 139.090 / 15.625 | 150.358 / 0.000 | 34.281 / 22.730 | 156,825 / 160,208 |
| noisy / sqlite | zstd-1 | 1.984 | 144.361 | 155.420 / 0.000 | 137.365 / 0.000 | 34.098 / 23.789 | 155,727 / 156,112 |
| noisy / sqlite | zstd-3 | 2.115 | 164.627 | 125.802 / 0.000 | 141.650 / 15.625 | 34.867 / 23.902 | 155,777 / 156,112 |
| noisy / sqlite | lz4-frame | 1.888 | 144.380 | 123.013 / 0.000 | 137.687 / 0.000 | 34.469 / 22.875 | 169,266 / 172,496 |
| repeated / sqlite | none | 1.806 | 143.762 | 131.641 / 0.000 | 136.717 / 0.000 | 34.023 / 22.598 | 131,377 / 131,384 |
| repeated / sqlite | gzip-9 | 2.146 | 143.493 | 107.406 / 0.000 | 132.698 / 0.000 | 34.410 / 22.863 | 69,250 / 70,096 |
| repeated / sqlite | zstd-1 | 2.177 | 332.760 | 137.388 / 0.000 | 319.533 / 15.625 | 34.492 / 23.414 | 68,470 / 70,096 |
| repeated / sqlite | zstd-3 | 1.808 | 148.039 | 127.075 / 0.000 | 123.688 / 0.000 | 34.445 / 23.703 | 68,417 / 70,096 |
| repeated / sqlite | lz4-frame | 2.293 | 177.134 | 132.675 / 31.250 | 161.077 / 0.000 | 34.086 / 22.770 | 69,732 / 70,096 |

Across compressed sqlite fixture observations, direct reads were 1.808–3.349 ms and restore + read was 121.363–332.760 ms. These are ranges across different fixtures/arms, not repeated-sample latency estimates. They show a material full-restore cost in this protocol, but do not establish an acceptable production threshold or codec-speed ranking.

Across compressed jsonl fixture observations, direct reads were 1.661–2.907 ms and restore + read was 138.291–283.337 ms. These are ranges across different fixtures/arms, not repeated-sample latency estimates. They show a material full-restore cost in this protocol, but do not establish an acceptable production threshold or codec-speed ranking.

### Separated codec, I/O, flush, verification and finalization phases

Values are milliseconds. `C/D` means compression/reopen restoration. I/O is timed stream read + write calls, not physical disk-device traffic. Verification is publication's round-trip, complete evidence and source rehash. Metadata is the manifest write/fsync; rename is publication only. Exact per-phase CPU, artifact verification, supervisor/whole-operation intervals and the publication verification decoder are also in every JSON sample. Phase sums may differ from totals because open/close, hashing and Python control work add overhead.

| Fixture / representation / arm | Codec C/D ms | Stream I/O C/D ms | Flush C/D ms | Publish verification ms | Metadata ms | Rename ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mixed / jsonl / none | 0.000 / 0.000 | 0.131 / 0.334 | 113.664 / 133.065 | 164.681 | 204.323 | 1.028 |
| mixed / jsonl / gzip-9 | 1.090 / 0.571 | 0.414 / 0.341 | 103.244 / 120.347 | 150.053 | 244.138 | 0.949 |
| mixed / jsonl / zstd-1 | 0.256 / 0.095 | 0.137 / 0.247 | 238.170 / 130.224 | 163.558 | 189.117 | 1.114 |
| mixed / jsonl / zstd-3 | 0.839 / 0.089 | 0.188 / 0.185 | 102.134 / 121.353 | 141.410 | 186.690 | 0.871 |
| mixed / jsonl / lz4-frame | 0.148 / 0.071 | 0.394 / 0.248 | 127.474 / 124.308 | 165.615 | 297.627 | 0.532 |
| noisy / jsonl / none | 0.000 / 0.000 | 0.250 / 0.178 | 117.270 / 136.483 | 141.993 | 217.307 | 0.403 |
| noisy / jsonl / gzip-9 | 2.922 / 0.231 | 0.641 / 0.163 | 132.496 / 148.179 | 159.312 | 196.133 | 0.520 |
| noisy / jsonl / zstd-1 | 0.320 / 0.198 | 0.187 / 0.370 | 118.921 / 134.183 | 138.997 | 219.855 | 0.396 |
| noisy / jsonl / zstd-3 | 0.463 / 0.868 | 0.158 / 1.301 | 125.665 / 123.134 | 173.756 | 291.355 | 0.466 |
| noisy / jsonl / lz4-frame | 0.248 / 0.061 | 0.605 / 0.191 | 119.907 / 142.834 | 150.417 | 220.642 | 0.966 |
| repeated / jsonl / none | 0.000 / 0.000 | 0.150 / 0.178 | 114.786 / 141.061 | 154.008 | 216.810 | 0.382 |
| repeated / jsonl / gzip-9 | 0.453 / 0.068 | 0.102 / 0.125 | 140.067 / 123.518 | 204.335 | 296.230 | 0.756 |
| repeated / jsonl / zstd-1 | 0.172 / 0.086 | 0.092 / 0.148 | 117.054 / 111.531 | 136.335 | 192.542 | 0.826 |
| repeated / jsonl / zstd-3 | 0.263 / 0.128 | 0.056 / 0.719 | 117.460 / 135.045 | 172.273 | 198.737 | 0.336 |
| repeated / jsonl / lz4-frame | 0.122 / 0.050 | 0.045 / 0.233 | 149.264 / 257.409 | 177.375 | 184.050 | 0.441 |
| incompressible / raw / none | 0.000 / 0.000 | 1.205 / 0.723 | 113.486 / 132.861 | 139.613 | 204.591 | 0.322 |
| incompressible / raw / gzip-9 | 1.978 / 0.299 | 0.561 / 0.318 | 113.397 / 121.201 | 165.089 | 188.217 | 0.325 |
| incompressible / raw / zstd-1 | 0.320 / 0.203 | 21.292 / 0.567 | 110.125 / 133.553 | 254.695 | 585.579 | 0.539 |
| incompressible / raw / zstd-3 | 0.248 / 0.229 | 0.823 / 0.813 | 154.844 / 135.284 | 152.539 | 207.523 | 0.355 |
| incompressible / raw / lz4-frame | 0.148 / 0.069 | 1.016 / 0.207 | 127.954 / 124.050 | 165.074 | 207.467 | 1.085 |
| mixed / sqlite / none | 0.000 / 0.000 | 0.853 / 0.835 | 141.242 / 135.403 | 156.841 | 215.863 | 0.541 |
| mixed / sqlite / gzip-9 | 1.627 / 0.235 | 0.451 / 0.935 | 124.414 / 136.131 | 143.788 | 186.050 | 0.349 |
| mixed / sqlite / zstd-1 | 0.257 / 0.269 | 0.153 / 1.312 | 90.831 / 110.383 | 157.478 | 189.090 | 0.346 |
| mixed / sqlite / zstd-3 | 0.724 / 0.116 | 0.267 / 0.952 | 215.714 / 149.674 | 145.680 | 318.790 | 0.747 |
| mixed / sqlite / lz4-frame | 0.169 / 0.056 | 0.460 / 0.955 | 121.949 / 115.448 | 145.064 | 184.342 | 0.350 |
| noisy / sqlite / none | 0.000 / 0.000 | 0.781 / 0.820 | 106.276 / 122.733 | 132.894 | 181.893 | 0.435 |
| noisy / sqlite / gzip-9 | 4.630 / 0.405 | 1.205 / 0.927 | 129.655 / 147.326 | 155.531 | 228.468 | 0.587 |
| noisy / sqlite / zstd-1 | 1.097 / 0.697 | 0.469 / 2.175 | 145.703 / 130.924 | 164.327 | 185.916 | 0.549 |
| noisy / sqlite / zstd-3 | 0.549 / 0.375 | 0.216 / 8.072 | 121.167 / 127.084 | 335.386 | 190.917 | 0.541 |
| noisy / sqlite / lz4-frame | 0.242 / 0.091 | 0.519 / 0.987 | 116.734 / 135.231 | 149.801 | 194.525 | 1.518 |
| repeated / sqlite / none | 0.000 / 0.000 | 9.845 / 0.758 | 120.940 / 134.833 | 120.797 | 213.658 | 0.576 |
| repeated / sqlite / gzip-9 | 0.879 / 0.140 | 0.102 / 0.854 | 105.686 / 130.395 | 146.007 | 182.902 | 0.983 |
| repeated / sqlite / zstd-1 | 0.719 / 0.081 | 0.161 / 1.237 | 130.823 / 211.622 | 147.839 | 191.644 | 1.071 |
| repeated / sqlite / zstd-3 | 0.439 / 0.223 | 0.105 / 1.490 | 121.874 / 120.071 | 132.983 | 183.844 | 1.271 |
| repeated / sqlite / lz4-frame | 0.280 / 0.049 | 0.134 / 0.707 | 124.025 / 159.049 | 145.618 | 181.736 | 0.956 |

Maximum child working set was **34.87 MiB**; committed memory **23.90 MiB**, below the enforced 512-MiB Windows job ceiling. All children report IDLE priority class 64 and hard job containment. Peaks include imports, hashing, verification and reads, not just the codec. Total process threads observed were **4**, the same in the uncompressed control; this observation is distinct from each codec's explicit single-thread configuration. Thread-level CPU attribution was not measured.

Largest partial + verification copy + manifest was **229,683 logical bytes** / **229,688 reported stream-allocation bytes**, excluding the separate original. Conservative peak owned-scratch charge was **225,960,826 bytes (215.49 MiB)**, including pinned environment/cache and retained earlier attempts, below 1 GiB. The reserve check preserves the observed operating 5-GiB free-space floor plus study headroom. No C: spill was used.

Tiny CPU samples can be zero at Windows process-clock granularity; they are not zero-work claims. Durable flush dominates many small-file intervals. Timed I/O calls do not establish device throughput, whole-machine impact, UI latency or approved coexistence. One codec child ran at a time with single-thread codec settings and finite deadlines. Shared workload remained uncontrolled; no other owner was stopped.

## Decision and later storage-owner work

Use **Zstandard level 1 as the first candidate for a later representative, quiet-window experiment**, because it gives the best combined fixture density here. Level 3 wins only the repeated SQLite fixture by 53 bytes, not the combined input. Gzip remains the existing retained representation. LZ4's density is weaker; these timings establish no offsetting production speed benefit. Do not enable any container representation from this result.

Before implementation, acquire non-cherry-picked frozen real specimens under declared age/content/size strata and measure at most eight / 128 MiB with five repetitions inside the existing guards. Establish eligible-byte coverage and approved read/CPU/I/O limits. Real-drive benefit and a deployable tradeoff remain **inconclusive**.

If that experiment supports integration, the smallest change belongs in the existing `ResearchStorage` index/admission/housekeeping/reopen/recovery owner: a versioned, original/encoded length+hash checked representation for completed, unprotected temporary SQLite segments; stage/verify under exclusive ownership; publish before acknowledging/removing an eligible original; restore exact SQLite into admitted bounded scratch for lookup. Keep active SQLite and legacy/retained gzip compatible. Do not add another storage engine or authority.

Required later tests include legacy/current representations; exact references/raw bodies/availability; active, pinned, pending-outcome and expiry-waiting behavior; index/manifest mismatch; crash before/after rename, index acknowledgment and original removal; disk-full/locked destinations; retry/restart/hot-journal recovery; concurrent read/write ownership; expansion/memory deadlines; quota/reserve/scratch accounting during overlap; resource yielding and controlled coexistence; rollback preserving originals; separately authorized installed native/browser acceptance. The unresolved existing five-second capture test remains a handoff to that owner. See [VERIFICATION.md](VERIFICATION.md) for the honest ledger.

Benchmark-only. Operating storage and settings are unchanged.
No space has yet been reclaimed by this lane.
