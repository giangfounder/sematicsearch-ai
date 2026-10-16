# Puter chat — 16/10/2026

## Có miễn phí không?

Puter dùng mô hình User-Pays: người dùng đăng nhập Puter và dùng hạn mức của chính
tài khoản đó. Mỗi tài khoản có hạn mức miễn phí hằng tháng. Đây không phải nguồn
LLM miễn phí vô hạn cho mọi request từ EC2.

Danh mục công khai được kiểm tra ngày 16/10/2026 có 1.072 model/biến thể, trong đó
19 ID có hậu tố `:free`. Hậu tố này biểu thị biến thể miễn phí theo nhà cung cấp,
vẫn chịu rate limit/quota và có thể bị gỡ bỏ. Ứng dụng đọc danh mục hiện tại qua
`puter.ai.listModels()`, không giả định tên model luôn tồn tại.

## Phân chia model

- Mặc định **Chỉ model miễn phí**. Câu chào ngắn ưu tiên Liquid LFM 2.5 2.6B;
  câu hỏi thông thường ưu tiên Gemma 4 26B A4B; so sánh/phân tích ưu tiên Gemma 4 31B.
  Chỉ chọn các ID `:free` đã xác nhận trong danh mục hiện tại. Qwen Flash và DeepSeek
  Flash là lựa chọn tiếp theo khi model ưu tiên không còn trong danh mục.
- Chọn model bằng quy tắc chạy tại trình duyệt, không phát sinh request AI để phân loại.
- **Dùng hạn mức · model tiết kiệm** là lựa chọn riêng của người dùng. So sánh chi phí
  metadata hiện tại giữa Gemini 2.5 Flash-Lite, GPT-4o mini và Gemini 3.5 Flash-Lite.
  Đây là chế độ có thể tính phí tài khoản Puter, không tự kích hoạt khi model miễn phí lỗi.
- Một lượt gửi có tối đa một request sinh câu trả lời. Không tự gọi nhiều model,
  không tự retry khi stream lỗi/đã có nội dung, không chuyển sang key server khi hết quota.
  Việc một model miễn phí còn trong danh mục không chứng minh model đó đang đáp ứng
  tốt hoặc đạt chất lượng tiếng Việt mong muốn; cần đánh giá bằng tài khoản thật.

## Giảm request và token

- Tải SDK khi mở màn hình chat; các màn hình khác không tải SDK Puter.
- Danh mục tải khi vào màn hình/tải lại, không tải theo mỗi câu hỏi. SDK có cache metadata.
- Giữ tối đa ba cặp hỏi/đáp hoàn tất trong prompt; loại các đáp án lỗi, bị dừng hoặc bị cắt.
- Giới hạn tổng prompt 12.000 ký tự JSON và câu hỏi 2.000 ký tự. Đây là giới hạn ký tự,
  không phải phép đo token chính xác. Không gọi thêm model để tóm tắt hội thoại.
- Giới hạn đầu ra 384 token cho câu thường, 768 cho phân tích, hoặc thấp hơn nếu model yêu cầu.
- Cache tối đa 20 kết quả hoàn tất trong RAM của màn hình, theo model, prompt và phiên bản
  dữ liệu. Cache bị xoá khi đóng màn hình/đổi nguồn dữ liệu; không ghi hội thoại ra storage.
- Gộp cập nhật stream theo animation frame; một request đang chạy tại một thời điểm.
  Nút Dừng, chuyển màn hình và deadline 45 giây đều hủy bằng AbortSignal.
- Phần đã sinh trước khi nhà cung cấp xử lý hủy vẫn có thể tính vào sử dụng.

## Dữ liệu bảng và embedding

**Dùng dữ liệu bảng** mặc định tắt. Bật tuỳ chọn sẽ cho phép gửi câu hỏi cùng tối đa
ba trích đoạn đến Puter/nhà cung cấp model. Đổi chế độ bắt đầu hội thoại mới.

`POST /v1/tables/{slug}/chat-context` yêu cầu phiên/quyền quản trị và kiểm tra sở hữu
bảng. Endpoint dùng BM25/entity/rules cục bộ, tắt understanding, rerank, embedding
và rewritten embedding. Trả các trường sản phẩm cho phép, tối đa 3.000 ký tự JSON,
không trả nguyên cột Excel/raw hay metadata bí mật. Response `Cache-Control: no-store`.

Truy xuất cục bộ có thể bỏ sót câu đồng nghĩa hơn so với tìm kiếm semantic. UI hiện
nguồn đã gửi; prompt yêu cầu model nói rõ khi dữ liệu thiếu và dẫn ID bản ghi.
Đây không phải bảo đảm model luôn đúng. Không dùng câu trả lời để tự sửa dữ liệu.

Puter chat không thay đổi model embedding đang hoạt động, không trộn vector và không
tự chạy lại catalog. API server/ingest vẫn dùng Gemini/GPT theo cấu hình backend.
Endpoint tương thích OpenAI/Anthropic của Puter yêu cầu gói trả phí; không coi chúng
là phương án thay miễn phí cho background job EC2.

## Sử dụng

Vào **Trò chuyện AI**, chờ danh mục tải và bấm **Kết nối Puter** để đăng nhập tài khoản
Puter của bạn. Mặc định dùng model miễn phí. Chỉ bật dữ liệu bảng khi muốn gửi các trích
đoạn liên quan. Không có key Puter/server nào nằm trong source frontend.

Kiểm thử dùng HTTP giả lập và SDK giả lập để không tiêu hao hạn mức. Trình duyệt thật
đã tải SDK/danh mục và xác nhận chọn model. Chưa xác nhận sinh câu trả lời thật khi
chưa đăng nhập tài khoản Puter của người dùng.

## Tài liệu chính thức

- [User-Pays](https://docs.puter.com/user-pays-model/)
- [Rate limits và quota](https://docs.puter.com/rate-limits-and-quotas/)
- [Danh mục và biến thể :free](https://docs.puter.com/AI/listModels/)
- [Chat, streaming và AbortSignal](https://docs.puter.com/AI/chat/)
- [Đăng nhập từ thao tác người dùng](https://docs.puter.com/Auth/signIn/)
