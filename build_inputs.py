"""Verify frozen source inputs without consulting the staging checkout."""
import hashlib,json
from pathlib import Path

def remind_linked_review(root,entry):
    """Always record a review reminder, never claim field verification or edit values."""
    import datetime,uuid
    root=Path(root)
    groups={
        'oauth_headers':['src/internal/accountheaders/policy.go','src/internal/auth/claude/anthropic_auth.go','src/internal/auth/claude/container_auth.go'],
        'go_executor_headers':['src/internal/accountheaders/policy.go','src/cmd/server/offline_header_policy.go'],
        'cc_version':['src/internal/accountheaders/policy.go','src/internal/runtime/executor/claude_executor_cloaking.go'],
    }
    names=sorted({name for files in groups.values() for name in files}|{'overlay-inputs.json','image/account_header_policy.json'})
    inputs={name:hashlib.sha256((root/name).read_bytes()).hexdigest() if (root/name).is_file() else None for name in names}
    record={'schema':1,'entry':entry,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'reminder_triggered':True,'verification_status':'pending','groups':groups,'input_sha256':inputs,
            'note':'构建前输入快照；三项必须同步核对，需变更时同步更新。不是请求实测或发布验收。'}
    folder=root/'evidence/build-reviews';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(uuid.uuid4().hex+'.json');path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print('[打包必查] OAuth 请求头覆盖 / Go 执行器请求头覆盖 / 正文 cc_version 版本覆盖：三项关联，必须同步核对、同步更新。',flush=True)
    print('[待确认] 核对来源、覆盖前后与最终发送值、版本及生成规则、映射和打包产物；独立协议值逐项说明。保留手改值，不自动修改请求。',flush=True)
    print('[记录] '+str(path)+'（已提醒；尚未核验，不代表实测通过）',flush=True)
    return record

def verify_source(root):
    source=root/'source'
    expected=json.loads((root/'source-inputs.json').read_text())['files']
    actual={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    if actual!=expected:
        changed=sorted(k for k in actual.keys()|expected.keys() if actual.get(k)!=expected.get(k))
        raise ValueError('frozen_source_changed: '+', '.join(changed[:8]))
    mapping=json.loads((root/'overlay-inputs.json').read_text())
    for name,target in mapping.items():
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('invalid_source_mapping')
        path=(root/target).resolve()
        if not path.is_relative_to((root/'src').resolve()) or not path.is_file():
            raise ValueError('external_overlay_input')
    return len(actual)
