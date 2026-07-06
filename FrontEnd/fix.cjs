const fs = require('fs');
let code = fs.readFileSync('bubble.txt', 'utf8');

// 1. Update signature
code = code.replace(
  'export default function MessageBubble({ message, onClearPendingFile }) {',
  'export default function MessageBubble({ message, onClearPendingFile, pendingFile, onConfirmFile, isLatest }) {'
);

const badReturnIndex = code.indexOf('  // AI Message\n  return (');
const badReturnIndex2 = code.indexOf('  // AI Message\r\n  return (');
const badIdx = badReturnIndex !== -1 ? badReturnIndex : badReturnIndex2;

if (badIdx === -1) {
    console.error('Could not find the injected return');
    process.exit(1);
}

let newCode = code.substring(0, badIdx);

newCode += `              {/* 카카오맵 링크 */}
              {message.mapCard.place_url && (
                <a
                  href={message.mapCard.place_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-center gap-1.5 text-xs font-medium text-[#005956] hover:bg-[#e4f4f3] transition bg-white"
                  style={{ padding: '8px', textDecoration: 'none' }}
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                  </svg>
                  카카오맵에서 크게 보기
                </a>
              )}
            </div>
          )}

          {/* 파일 다운로드 링크 */}
          {message.fileDownload && (
            <div
              className="flex items-center gap-2 rounded-lg border border-blue-100 bg-blue-50"
              style={{ marginTop: '14px', padding: '10px 14px' }}
            >
              <svg className="h-5 w-5 text-blue-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01-.01.01m5.699-9.941-7.81 7.81a1.5 1.5 0 002.112 2.13" />
              </svg>
              <button
                type="button"
                onClick={() =>
                  downloadFileWithAuth(message.fileDownload.url, message.fileDownload.filename)
                }
                className="text-blue-600 underline underline-offset-2 hover:text-blue-800 transition text-sm font-medium truncate"
              >
                {message.fileDownload.filename}
              </button>
            </div>
          )}

          {/* 파일 전송 확인 버튼 (show_buttons=false 인 단일 파일 제안, 대기 중일 때만 표시) */}
          {message.fileOffer && !message.fileOffer.show_buttons && isLatest && pendingFile && (
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                onClick={() => onConfirmFile(pendingFile, true)}
                className="flex items-center gap-1.5 rounded-lg border text-sm font-bold transition px-4 py-2 border-[#005956] text-[#005956] bg-[#f0f9f8] hover:bg-[#e2f1f0]"
              >
                네, 주세요!
              </button>
              <button
                onClick={() => onConfirmFile(pendingFile, false)}
                className="flex items-center gap-1.5 rounded-lg border text-sm font-bold transition px-4 py-2 border-slate-300 text-slate-600 bg-slate-50 hover:bg-slate-100"
              >
                아니요
              </button>
            </div>
          )}

          {/* 파일 선택 버튼 (사용자가 '응' 확인 후에만 표시) */}
          {message.fileOffer && message.fileOffer.show_buttons && message.fileOffer.files && message.fileOffer.files.length > 0 && (
            <div style={{ marginTop: '14px' }}>
              <p className="text-xs text-slate-400" style={{ marginBottom: '8px' }}>원하시는 파일을 선택해 주세요.</p>
              <div className="flex flex-wrap gap-2">
                {message.fileOffer.files.map((filename) => {
                  const stem = filename.replace(/\\.[^/.]+$/, '')
                  const isDone = downloadedFiles.has(filename)
                  return (
                    <button
                      key={filename}
                      type="button"
                      disabled={isDone}
                      onClick={async () => {
                        await downloadFileWithAuth(\`/api/files/\${message.fileOffer.topic}/\${filename}\`, filename)
                        setDownloadedFiles(prev => new Set([...prev, filename]))
                        if (onClearPendingFile) onClearPendingFile()
                      }}
                      className="flex items-center gap-1.5 rounded-lg border text-sm font-medium transition"
                      style={{
                        padding: '6px 12px',
                        borderColor: isDone ? '#a0aec0' : '#005956',
                        color: isDone ? '#a0aec0' : '#005956',
                        backgroundColor: isDone ? '#f8f8f8' : '#f0f9f8',
                        cursor: isDone ? 'default' : 'pointer',
                      }}
                    >
                      <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                      </svg>
                      {isDone ? \`\${stem} ✓\` : stem}
                    </button>
                  )
                })}

                {/* 전체 다운로드 버튼 (파일 2개 이상일 때만) */}
                {message.fileOffer.files.length > 1 && (
                  <button
                    type="button"
                    disabled={message.fileOffer.files.every(f => downloadedFiles.has(f))}
                    onClick={async () => {
                      for (const filename of message.fileOffer.files) {
                        if (!downloadedFiles.has(filename)) {
                          await downloadFileWithAuth(\`/api/files/\${message.fileOffer.topic}/\${filename}\`, filename)
                        }
                      }
                      setDownloadedFiles(new Set(message.fileOffer.files))
                      if (onClearPendingFile) onClearPendingFile()
                    }}
                    className="flex items-center gap-1.5 rounded-lg border text-sm font-medium transition"
                    style={{
                      padding: '6px 12px',
                      borderColor: message.fileOffer.files.every(f => downloadedFiles.has(f)) ? '#a0aec0' : '#1a5276',
                      color: message.fileOffer.files.every(f => downloadedFiles.has(f)) ? '#a0aec0' : '#1a5276',
                      backgroundColor: message.fileOffer.files.every(f => downloadedFiles.has(f)) ? '#f8f8f8' : '#eaf2f8',
                      cursor: message.fileOffer.files.every(f => downloadedFiles.has(f)) ? 'default' : 'pointer',
                    }}
                  >
                    <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                    </svg>
                    {message.fileOffer.files.every(f => downloadedFiles.has(f)) ? '모두 다운로드 완료 ✓' : '전부 다운로드'}
                  </button>
                )}
              </div>
            </div>
          )}

          <div className="flex justify-between items-end" style={{ marginTop: '12px' }}>
            <span className="text-xs text-slate-400">{message.time}</span>
            <MessageActions messageId={message.messageId} content={message.content} />
          </div>
        </div>
      </div>
    </div>
  )
}
`;

fs.writeFileSync('src/components/chat/MessageBubble.jsx', newCode);
console.log('Fixed file.');
