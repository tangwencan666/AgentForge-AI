"""Immutable Docker controls and approval digest; callers may only reduce resources."""
import hashlib
import json
import re
from decimal import Decimal
from app.schemas.sandbox import POLICY_VERSION, ResourceLimits

OWNER_LABEL = "agentforge.sandbox.policy"
EXECUTION_LABEL = "agentforge.sandbox.execution"
OUTPUT_LIMIT = 1024 * 1024
SUMMARY_LIMIT = 4096
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out", "output_limit", "needs_reconciliation"})

# Deliberately smaller than Docker's default profile. New syscalls require a reviewed
# image/policy change. mount, ptrace, bpf, keyctl, perf, setns, unshare are absent.
_SYSCALLS = "read write readv writev open openat close close_range fstat newfstatat stat lstat statx lseek mmap mprotect munmap mremap madvise brk rt_sigaction rt_sigprocmask rt_sigreturn rt_sigsuspend sigaltstack pread64 pwrite64 access faccessat faccessat2 pipe pipe2 select pselect6 poll ppoll dup dup2 dup3 nanosleep clock_nanosleep clock_gettime getitimer setitimer alarm getpid getppid gettid sendfile shutdown bind connect listen accept accept4 getsockname getpeername setsockopt getsockopt sendto recvfrom sendmsg recvmsg fork vfork execve execveat exit exit_group wait4 waitid kill tgkill tkill uname fcntl flock fsync fdatasync truncate ftruncate getdents getdents64 getcwd chdir fchdir rename renameat renameat2 mkdir mkdirat rmdir creat link linkat unlink unlinkat symlink symlinkat readlink readlinkat chmod fchmod fchmodat chown fchown lchown fchownat umask gettimeofday getrlimit getrusage sysinfo times getuid getgid geteuid getegid getgroups setpgid getpgrp getsid setsid capget getresuid getresgid statfs fstatfs prctl arch_prctl set_tid_address set_robust_list get_robust_list futex futex_waitv sched_yield sched_getaffinity sched_getparam sched_getscheduler sched_get_priority_max sched_get_priority_min sched_rr_get_interval getrandom restart_syscall prlimit64 rseq membarrier epoll_create epoll_create1 epoll_ctl epoll_wait epoll_pwait eventfd eventfd2 timerfd_create timerfd_settime timerfd_gettime utime utimes utimensat getcpu".split()
SECCOMP = {
    "defaultAction": "SCMP_ACT_ERRNO", "defaultErrnoRet": 1,
    "archMap": [{"architecture": "SCMP_ARCH_X86_64", "subArchitectures": ["SCMP_ARCH_X86", "SCMP_ARCH_X32"]},
                {"architecture": "SCMP_ARCH_AARCH64", "subArchitectures": ["SCMP_ARCH_ARM"]}],
    "syscalls": [{"names": _SYSCALLS, "action": "SCMP_ACT_ALLOW"},
                 {"names": ["clone"], "action": "SCMP_ACT_ALLOW",
                  "args": [{"index": 0, "value": 2114060416, "valueTwo": 0, "op": "SCMP_CMP_MASKED_EQ"}]},
                 {"names": ["clone3"], "action": "SCMP_ACT_ERRNO", "errnoRet": 38},
                 *[{"names": ["socket", "socketpair"], "action": "SCMP_ACT_ALLOW",
                    "args": [{"index": 0, "value": family, "op": "SCMP_CMP_EQ"}]} for family in (1, 2, 10)],
                 {"names": ["ioctl"], "action": "SCMP_ACT_ALLOW",
                  "args": [{"index": 1, "value": 0x5401, "op": "SCMP_CMP_EQ"}]},
                 # CPython _Py_fopen_obj marks the script FD close-on-exec through
                 # ioctl(FIOCLEX); this only sets an existing descriptor flag.
                 {"names": ["ioctl"], "action": "SCMP_ACT_ALLOW",
                  "args": [{"index": 1, "value": 0x5451, "op": "SCMP_CMP_EQ"}]}],
}


class PolicyViolation(Exception):
    """Only static reason identifiers may leave the control plane."""


def operation_digest(code_hash, language, timeout_seconds, resource_limits, image_id):
    document = {"code_hash": code_hash, "language": language, "timeout_seconds": timeout_seconds,
                "resource_limits": resource_limits, "image_id": image_id, "policy_version": POLICY_VERSION}
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_image(image_id):
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise PolicyViolation("IMAGE_NOT_APPROVED")


def assert_runner_lease(row, owner, at):
    if (row.runner_owner != owner or row.status not in {"starting", "running"}
            or row.runner_lease_until is None or row.runner_lease_until <= at):
        raise PolicyViolation("RUNNER_LEASE_LOST")


def validate_execution(row, approval, task, settings):
    """Revalidate private durable input, policy, independent approval and quota."""
    from app.services.tasks import now
    validate_image(settings.sandbox_image_id)
    try:
        limits = ResourceLimits.model_validate(row.resource_limits)
    except Exception:
        raise PolicyViolation("INVALID_RESOURCE_LIMITS") from None
    if row.language != "python" or row.policy_version != POLICY_VERSION or not 1 <= row.timeout_seconds <= 120:
        raise PolicyViolation("INVALID_EXECUTION_POLICY")
    if not row.code or len(row.code.encode()) > 65536 or hashlib.sha256(row.code.encode()).hexdigest() != row.code_hash:
        raise PolicyViolation("CODE_HASH_MISMATCH")
    digest = operation_digest(row.code_hash, row.language, row.timeout_seconds, limits.model_dump(), settings.sandbox_image_id)
    if row.operation_hash != digest:
        raise PolicyViolation("OPERATION_CHANGED")
    if not approval or approval.id != row.approval_reference or approval.task_id != task.id or approval.tenant_id != row.tenant_id:
        raise PolicyViolation("APPROVAL_REQUIRED")
    if approval.status != "approved" or approval.policy_version != POLICY_VERSION or approval.operation_hash != digest or approval.expires_at <= now():
        raise PolicyViolation("APPROVAL_REQUIRED")
    if approval.decided_by != "sandbox-reviewer" or approval.decided_by == row.requester or row.requester != "local-admin":
        raise PolicyViolation("EXECUTION_FORBIDDEN")
    if row.tenant_id != task.tenant_id or task.options.get("execution_mode") != "sandbox" or task.is_mock:
        raise PolicyViolation("EXECUTION_FORBIDDEN")
    reserved = Decimal(str(limits.cpu)) * Decimal(row.timeout_seconds)
    if row.reserved_cpu_seconds != reserved or reserved > settings.sandbox_daily_cpu_seconds:
        raise PolicyViolation("SANDBOX_BUDGET")
    return limits


def create_options(image_id, execution_id, limits):
    validate_image(image_id)
    limits = ResourceLimits.model_validate(limits)
    return dict(image=image_id, name="agentforge-p3-exec-" + execution_id.hex,
        command=["python", "-I", "-S", "/opt/agentforge/launcher.py"], entrypoint=[],
        user="10001:10001", working_dir="/workspace", environment={"LANG": "C.UTF-8", "TZ": "UTC"}, use_config_proxy=False,
        network_mode="none", ipc_mode="private", privileged=False, read_only=True, cap_drop=["ALL"], cap_add=[],
        security_opt=["no-new-privileges:true", "seccomp=" + json.dumps(SECCOMP, separators=(",", ":"))],
        nano_cpus=int(limits.cpu * 1_000_000_000), mem_limit=limits.memory_mb * 1024 * 1024,
        memswap_limit=limits.memory_mb * 1024 * 1024, pids_limit=limits.pids,
        tmpfs={"/workspace": "rw,nosuid,nodev,noexec,size=67108864,uid=10001,gid=10001,mode=700",
               "/tmp": "rw,nosuid,nodev,noexec,size=16777216,uid=10001,gid=10001,mode=700"},
        volumes={}, devices=[], stdin_open=True, tty=False, detach=True,
        labels={OWNER_LABEL: POLICY_VERSION, EXECUTION_LABEL: str(execution_id)},
        log_config={"Type": "none", "Config": {}},
        ulimits=[{"Name": "nofile", "Soft": 128, "Hard": 128}, {"Name": "core", "Soft": 0, "Hard": 0}])


def verify_container(attrs, image_id, limits, execution_id):
    """Inspect after create, before start. A mismatch prevents any code injection."""
    limits = ResourceLimits.model_validate(limits)
    host, config = attrs.get("HostConfig", {}), attrs.get("Config", {})
    opts = create_options(image_id, execution_id, limits)
    safe = (attrs.get("Image") == image_id and config.get("User") == "10001:10001"
        and config.get("Cmd") == opts["command"] and not config.get("Entrypoint")
        and config.get("Labels", {}).get(OWNER_LABEL) == POLICY_VERSION
        and config.get("Labels", {}).get(EXECUTION_LABEL) == str(execution_id)
        and host.get("NetworkMode") == "none" and not host.get("Privileged")
        and host.get("ReadonlyRootfs") is True and host.get("CapDrop") == ["ALL"] and not host.get("CapAdd")
        and set(host.get("SecurityOpt", [])) == set(opts["security_opt"])
        and host.get("NanoCpus") == opts["nano_cpus"] and host.get("Memory") == opts["mem_limit"]
        and host.get("MemorySwap") == opts["memswap_limit"] and host.get("PidsLimit") == limits.pids
        and not host.get("Binds") and not host.get("Mounts") and not attrs.get("Mounts")
        and not host.get("Devices") and not host.get("PidMode") and host.get("IpcMode") == "private"
        and not host.get("UTSMode") and not host.get("PortBindings")
        and host.get("LogConfig", {}).get("Type") == "none" and host.get("Tmpfs") == opts["tmpfs"])
    if not safe:
        raise PolicyViolation("DOCKER_POLICY_MISMATCH")


def verify_attestation(data, limits):
    limits = ResourceLimits.model_validate(limits)
    expected_cpu = int(limits.cpu * 100000)
    if not (data.get("uid") == 10001 and data.get("gid") == 10001 and data.get("root_read_only") is True
            and data.get("seccomp") == 2 and data.get("no_new_privileges") == 1
            and all(data.get(name) == "0000000000000000" for name in ("cap_eff", "cap_prm", "cap_inh", "cap_amb"))
            and data.get("memory_max") == limits.memory_mb * 1024 * 1024 and data.get("pids_max") == limits.pids
            and data.get("memory_swap_max") == 0 and data.get("interfaces") == ["lo"]
            and data.get("cpu_quota") == expected_cpu and data.get("cpu_period") == 100000):
        raise PolicyViolation("RUNTIME_ISOLATION_UNVERIFIED")
