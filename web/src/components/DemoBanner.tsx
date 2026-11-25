// 포트폴리오 데모 안내 띠 (모드 demo 빌드에서만 보인다).
// 원래 서비스는 AWS(Bedrock·Textract·Lambda·DynamoDB)에서 서류를 처리했다. 데모는 서버 없이
// 그 처리 결과 예시(docs/examples/)를 재생하므로, 어떤 파일을 올려도 같은 예시 작업을 보여 준다.
import jobExample from "../../../docs/examples/job_waiting_approval.json";
import { navigate } from "../route";

export const REPO_URL = "https://github.com/GaMaius/aws.ai.maestro.6";
export const DEMO_JOB_ID = (jobExample as { job_id: string }).job_id;

export function DemoBanner() {
  return (
    <aside className="demo-banner" aria-label="데모 안내">
      <p className="demo-banner-text">
        <strong>포트폴리오 데모</strong>
        <span>
          원래 서비스는 AWS(Bedrock · Textract · Lambda · DynamoDB)에서 동작했습니다. 이 화면은 서버 없이 실제 처리 결과
          예시를 재생하며, 어떤 파일을 올려도 같은 예시 작업을 보여 줍니다.
        </span>
      </p>
      <div className="demo-banner-actions">
        <button type="button" className="demo-banner-try" onClick={() => navigate(`/jobs/${DEMO_JOB_ID}`)}>
          예시 작업 바로 보기
        </button>
        <a className="demo-banner-link" href={REPO_URL} target="_blank" rel="noreferrer">
          설계와 코드
        </a>
      </div>
    </aside>
  );
}
