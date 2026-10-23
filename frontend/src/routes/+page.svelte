<script>
    import Button from '#lib/components/Button.svelte';

    const features = [
        {
            icon: '👨🏻‍💻',
            title: 'จัดการ Self-Service',
            text: 'ควบคุมการสร้าง, เริ่มทำงาน, หยุดทำงาน และลบอินสแตนซ์ GNS3 ของคุณได้ตามต้องการ'
        },
        {
            icon: '🌍',
            title: 'เข้าถึงได้ทุกที่ ทุกเวลา',
            text: 'เชื่อมต่อกับ GNS3 ของคุณได้จากทุกพื้นที่ เพียงแค่เชื่อมต่ออินเทอร์เน็ต'
        },
        {
            icon: '📝',
            title: 'แบบทดสอบจากผู้สอน',
            text: 'ยกระดับการเรียนรู้ด้วยแบบทดสอบสุดท้าทาย ผู้สอนสร้างโจทย์ แล้วให้ผู้เรียนแก้ไขปัญหา'
        },
        {
            icon: '✨',
            title: 'ประหยัดทรัพยากร',
            text: 'ไม่ต้องกังวลเรื่องของฮาร์ดแวร์ สามารถใช้งานได้บนคลาวด์โดยตรง'
        }
    ];
</script>

<svelte:head>
    <title>หน้าหลัก - NetLab</title>
</svelte:head>

<div class="flex justify-center items-center min-h-screen w-full">
    <div class="text-center max-w-6xl p-6">
        <video autoplay loop muted playsinline class="inline-block w-auto mb-12">
            <source src="/animation/netlab.mp4" type="video/mp4" />
        </video>
        <p class="text-gray-800 text-2xl">
            ยกระดับทักษะทางด้านเครือข่ายด้วยแล็บเสมือนจริง บน <span class="text-cyan-600">GNS3</span> รวมทั้ง
        </p>
        <p class="text-gray-800 text-2xl mb-6">
            ฝึกฝนจริงได้ทุกที่ทุกเวลา ผ่าน <span class="text-amber-600">Amazon Web Services</span>
        </p>
        <div class="flex gap-4 justify-center">
            <Button href="/signin">🦎 เริ่มต้นทำแล็บ</Button>
            <a
                href="#about"
                class="border hover:bg-gray-50 transition-colors duration-200 ease-in-out px-4 py-3 rounded-xl text-sm"
            >
                เกี่ยวกับแพลตฟอร์ม
            </a>
        </div>
    </div>
</div>

<div id="about" class="max-w-6xl mx-auto px-6 py-28 border-t">
    <p class="text-center text-gray-800 text-4xl mb-2">ฟีเจอร์ของแพลตฟอร์ม</p>
    <p class="text-center text-xl text-gray-600 mb-20">
        สัมผัสประสบการณ์สภาพแวดล้อมการเรียนรู้ที่ครอบคลุม ออกแบบมาสำหรับผู้ใช้งานด้านเครือข่ายโดยเฉพาะ
    </p>
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
        {#each features as feature (feature.title)}
            <div>
                <p class="text-4xl mb-6">{feature.icon}</p>
                <p class="text-2xl text-gray-800 mb-4">{feature.title}</p>
                <p class="text-base text-gray-600">{feature.text}</p>
            </div>
        {/each}
    </div>
</div>

<div class="max-w-6xl mx-auto px-6 py-28 border-t">
    <p class="text-center text-gray-800 text-4xl mb-10">พร้อมที่จะเริ่มทำแล็บหรือยัง?</p>
    <div class="flex justify-center">
        <a
            href="/signin"
            class="bg-gray-800 hover:bg-gray-900 transition-colors duration-200 ease-in-out text-white px-10 py-6 rounded-2xl text-xl"
        >
            เริ่มต้นใช้งานเลย ->
        </a>
    </div>
</div>
