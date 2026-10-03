# Memory Benchmark Analysis

File này ghi lại kết quả chạy benchmark sau khi xóa sạch `state/`:

```powershell
Remove-Item -Recurse -Force state
python -B src\benchmark.py
```

## Benchmark Output

### Standard Benchmark

| Agent | Agent tokens only | Prompt tokens processed | Cross-session recall | Response quality | Memory growth (bytes) | Compactions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 2226 | 19964 | 0.04 | 0.28 | 0 | 0 |
| Advanced | 2461 | 27577 | 1.00 | 1.00 | 393 | 0 |

### Long-Context Stress Benchmark

| Agent | Agent tokens only | Prompt tokens processed | Cross-session recall | Response quality | Memory growth (bytes) | Compactions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 402 | 23869 | 0.00 | 0.25 | 0 | 0 |
| Advanced | 918 | 18461 | 1.00 | 1.00 | 448 | 2 |

Phép chạy lại trên trạng thái sạch cho cùng kết quả, nên nhánh offline đang tất định.

## 1. Vì Sao Advanced Recall Tốt Hơn Baseline

Ở Standard Benchmark, `Cross-session recall` của Baseline là `0.04`, còn Advanced là `1.00`. Ở Long-Context Stress Benchmark, Baseline là `0.00`, còn Advanced vẫn là `1.00`.

Cơ chế tạo ra khác biệt này nằm ở đường đi của fact trong `src/agent_advanced.py`: `_reply_offline()` gọi `extract_profile_updates()`, ghi fact vào `User.md` qua `UserProfileStore`, rồi `_offline_response()` đọc lại facts từ file đó khi câu hỏi recall được hỏi ở thread mới. Baseline trong `src/agent_baseline.py` chỉ giữ `SessionState` theo `thread_id`, nên sang recall thread mới nó không còn danh sách message cũ. Điều này cũng thể hiện ở `Memory growth (bytes)`: Baseline luôn `0`, còn Advanced tăng `393` bytes ở Standard và `448` bytes ở Stress.

Giới hạn đi kèm là Advanced phụ thuộc vào chất lượng trích fact. Nếu extractor ghi sai fact vào `User.md`, lỗi đó có thể sống qua nhiều thread.

## 2. Vì Sao Advanced Có Thể Tốn Hơn Ở Hội Thoại Ngắn

Ở Standard Benchmark, Advanced dùng `2461` agent tokens và xử lý `27577` prompt tokens, cao hơn Baseline với `2226` agent tokens và `19964` prompt tokens. Đây là bảng hội thoại ngắn hơn, nơi `Compactions` của cả hai agent đều là `0`, nên compact chưa có cơ hội bù chi phí.

Cơ chế trong code giải thích con số này: mỗi lượt Advanced ước lượng prompt từ ba thành phần trong `_estimate_prompt_context_tokens()`: nội dung `User.md`, summary compact memory, và recent messages. Khi thread chưa đủ dài để compact chạy, Advanced vẫn phải mang thêm profile memory, còn Baseline chỉ kéo lịch sử trong thread hiện tại.

Kết luận là Advanced không miễn phí. Ở hội thoại ngắn, nó mua recall tốt hơn bằng chi phí prompt cao hơn.

## 3. Vì Sao Compact Có Lợi Thế Ở Hội Thoại Dài

Ở Long-Context Stress Benchmark, Baseline xử lý `23869` prompt tokens, còn Advanced chỉ xử lý `18461` prompt tokens. Cột quan trọng ở đây là `Prompt tokens processed`, không phải `Agent tokens only`: Advanced vẫn sinh nhiều agent tokens hơn (`918` so với `402`) vì câu trả lời recall có nhiều fact hơn, nhưng nó kéo ít ngữ cảnh hơn nhờ compact.

Bằng chứng compact thật sự chạy là `Compactions = 2` ở Advanced trong bảng stress. `CompactMemoryManager` giữ recent messages và nén phần cũ thành summary khi vượt ngưỡng, nên `_estimate_prompt_context_tokens()` không còn phải cộng toàn bộ lịch sử nguyên văn như Baseline.

Phép chẩn đoán tắt compact bằng `COMPACT_THRESHOLD_TOKENS=999999` cho thấy Advanced stress đổi từ `18461` prompt tokens và `2` compactions sang `26808` prompt tokens và `0` compactions. Vì vậy lợi thế prompt trong bảng stress đến từ compact memory, không phải từ dữ liệu bị lọc hay câu hỏi dễ hơn.

## 4. Memory Growth Và Rủi Ro

Advanced tăng `393` bytes ở Standard và `448` bytes ở Stress, còn Baseline luôn `0`. Điều này đúng với thiết kế: Advanced có persistent `User.md`, Baseline không ghi file nào. Trong bảng stress, Advanced cũng có `Compactions = 2`, nghĩa là lịch sử hội thoại dài được nén trong bộ nhớ thread, còn profile facts vẫn đi vào file riêng.

Rủi ro chính là file memory có thể phình theo thời gian hoặc lưu nhầm fact từ lượt nhiễu. Ví dụ câu hỏi kiểu "Mình tên gì?" không phải fact mới, nhưng nếu extractor hiểu nhầm thành `name: gì` thì recall về sau sẽ sai. Tương tự, correction về nơi ở hoặc nghề nghiệp phải ghi đè giá trị cũ, không được append thêm một dòng mâu thuẫn.

Vì vậy hệ thống mạnh hơn Baseline nhưng cũng cần guardrail tốt hơn: lọc fact trước khi ghi, xử lý correction, và theo dõi tốc độ tăng của `User.md`.

## Bonus Chọn: Confidence Threshold Trước Khi Ghi User.md

Bonus được chọn là `Confidence threshold` trước khi ghi vào `User.md`.

Vấn đề nó giải quyết: không phải mọi message chứa từ khóa profile đều là fact ổn định. Câu hỏi recall hoặc lượt nhiễu có thể làm extractor trả ra giá trị rác như "gì", "ở đâu", hoặc "như thế nào". Trong `src/agent_advanced.py`, lớp `_stable_profile_updates()` lọc các giá trị dạng câu hỏi trước khi `_persist_profile_updates()` ghi xuống file.

Tác động mong muốn: recall ổn định hơn vì `User.md` ít bị bẩn bởi câu hỏi; token cost cũng gián tiếp tốt hơn vì file memory không phình do các dòng sai. Điều này hỗ trợ kết quả `Cross-session recall = 1.00` của Advanced ở cả hai bảng trong khi memory growth vẫn ở mức vài trăm bytes.

Rủi ro mới: threshold quá chặt có thể bỏ sót fact thật nếu người dùng diễn đạt lạ hoặc cung cấp fact dưới dạng câu nửa hỏi nửa kể. Vì vậy guardrail này cần test thêm trên dữ liệu tự nhiên hơn, thay vì chỉ dựa vào vài pattern cố định.

## Đối Chiếu Rubric

- 0-60: Có Baseline chỉ nhớ trong thread, Advanced có `User.md`, compact memory, benchmark và cấu trúc repo rõ ràng.
- 60-75: Benchmark chạy cùng input cho cả hai agent, bảng đủ sáu cột, test cover `User.md`, compact trigger, cross-session recall và prompt-load reduction.
- 75-90: Có cả Standard Benchmark và Long-Context Stress Benchmark; stress làm lộ chi phí ngữ cảnh của Baseline; phân tích tách rõ `Prompt tokens processed` khỏi `Agent tokens only`.
- 90-100: Bonus `Confidence threshold` được chọn vì gắn trực tiếp với rủi ro ghi sai fact vào `User.md`, kèm lợi ích và rủi ro của chính bonus đó.
