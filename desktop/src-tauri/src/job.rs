//! Windows job object that kills the engine if the desktop app dies.
//!
//! Graceful shutdown normally stops the engine first; the job only guarantees
//! that a crash or a forced kill of the shell cannot leave an orphaned engine
//! holding the Telegram session file.

use std::os::windows::io::AsRawHandle;
use std::process::Child;
use std::sync::OnceLock;

use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

struct Job(HANDLE);
// The handle is only used for AssignProcessToJobObject, which is thread-safe.
unsafe impl Send for Job {}
unsafe impl Sync for Job {}

static JOB: OnceLock<Option<Job>> = OnceLock::new();

fn job() -> Option<&'static Job> {
    JOB.get_or_init(|| unsafe {
        let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if handle.is_null() {
            return None;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok = SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const core::ffi::c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if ok == 0 {
            return None;
        }
        // Intentionally never closed: closing it is what kills the engine.
        Some(Job(handle))
    })
    .as_ref()
}

pub fn attach(child: &Child) {
    if let Some(job) = job() {
        unsafe {
            AssignProcessToJobObject(job.0, child.as_raw_handle() as HANDLE);
        }
    }
}
